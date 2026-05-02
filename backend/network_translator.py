"""
Archmorph – Network Topology Translator
Translates AWS VPC / GCP VPC networking constructs to Azure VNet equivalents.

Handles:
  - VPC → VNet with CIDR planning
  - Subnet mapping by zone (public/private/database)
  - Security Groups → NSG rules with priority assignment
  - Route tables (IGW, NAT, VPN/ExpressRoute, peering)
  - GCP auto-mode/custom-mode VPC → Azure VNet
  - Hub-spoke topology detection
  - CIDR non-overlap validation
"""

from __future__ import annotations

import ipaddress
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from source_provider import normalize_source_provider

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────

@dataclass
class SubnetSpec:
    name: str
    cidr: str
    zone_type: str  # "public" | "private" | "database"
    availability_zone: str = ""
    service_endpoints: List[str] = field(default_factory=list)
    delegation: Optional[str] = None
    nat_gateway: bool = False
    nsg_name: Optional[str] = None


@dataclass
class NSGRule:
    name: str
    priority: int
    direction: str  # "Inbound" | "Outbound"
    access: str  # "Allow" | "Deny"
    protocol: str  # "Tcp" | "Udp" | "*"
    source_address: str
    source_port: str
    destination_address: str
    destination_port: str
    description: str = ""


@dataclass
class NSGSpec:
    name: str
    rules: List[NSGRule] = field(default_factory=list)


@dataclass
class RouteSpec:
    name: str
    address_prefix: str
    next_hop_type: str  # "Internet" | "VirtualAppliance" | "VnetLocal" | "VirtualNetworkGateway" | "None"
    next_hop_address: Optional[str] = None


@dataclass
class RouteTableSpec:
    name: str
    routes: List[RouteSpec] = field(default_factory=list)
    associated_subnets: List[str] = field(default_factory=list)


@dataclass
class NATGatewaySpec:
    name: str
    public_ip_name: str
    associated_subnets: List[str] = field(default_factory=list)


@dataclass
class NetworkTopology:
    vnet_name: str
    vnet_cidr: str
    subnets: List[SubnetSpec]
    nsgs: List[NSGSpec]
    route_tables: List[RouteTableSpec]
    nat_gateway: Optional[NATGatewaySpec]
    topology_type: str  # "hub-spoke" | "flat" | "mesh"
    source_provider: str
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "vnet": {
                "name": self.vnet_name,
                "cidr": self.vnet_cidr,
                "subnets": [
                    {
                        "name": s.name,
                        "cidr": s.cidr,
                        "zone_type": s.zone_type,
                        "availability_zone": s.availability_zone,
                        "service_endpoints": s.service_endpoints,
                        "delegation": s.delegation,
                        "nat_gateway": s.nat_gateway,
                        "nsg_name": s.nsg_name,
                    }
                    for s in self.subnets
                ],
            },
            "nsgs": [
                {
                    "name": nsg.name,
                    "rules": [
                        {
                            "name": r.name,
                            "priority": r.priority,
                            "direction": r.direction,
                            "access": r.access,
                            "protocol": r.protocol,
                            "source_address": r.source_address,
                            "source_port": r.source_port,
                            "destination_address": r.destination_address,
                            "destination_port": r.destination_port,
                            "description": r.description,
                        }
                        for r in nsg.rules
                    ],
                }
                for nsg in self.nsgs
            ],
            "route_tables": [
                {
                    "name": rt.name,
                    "routes": [
                        {
                            "name": r.name,
                            "address_prefix": r.address_prefix,
                            "next_hop_type": r.next_hop_type,
                            "next_hop_address": r.next_hop_address,
                        }
                        for r in rt.routes
                    ],
                    "associated_subnets": rt.associated_subnets,
                }
                for rt in self.route_tables
            ],
            "nat_gateway": (
                {
                    "name": self.nat_gateway.name,
                    "public_ip_name": self.nat_gateway.public_ip_name,
                    "associated_subnets": self.nat_gateway.associated_subnets,
                }
                if self.nat_gateway
                else None
            ),
            "topology_type": self.topology_type,
            "source_provider": self.source_provider,
            "warnings": self.warnings,
        }


# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

DEFAULT_VNET_CIDR = "10.0.0.0/16"
DEFAULT_SUBNET_PREFIX = 24

# AWS protocol numbers → Azure protocol names
_AWS_PROTOCOL_MAP = {
    "-1": "*",
    "6": "Tcp",
    "17": "Udp",
    "1": "Icmp",
    "tcp": "Tcp",
    "udp": "Udp",
    "icmp": "Icmp",
    "all": "*",
}

# Well-known port names for rule naming
_PORT_NAMES = {
    "22": "SSH",
    "80": "HTTP",
    "443": "HTTPS",
    "3389": "RDP",
    "3306": "MySQL",
    "5432": "PostgreSQL",
    "1433": "MSSQL",
    "6379": "Redis",
    "27017": "MongoDB",
    "8080": "HTTP-Alt",
    "8443": "HTTPS-Alt",
}

# GCP auto-mode subnet CIDRs by region (first 4 for typical deployments)
_GCP_AUTO_MODE_CIDRS = {
    "us-central1": "10.128.0.0/20",
    "europe-west1": "10.132.0.0/20",
    "asia-east1": "10.140.0.0/20",
    "us-east1": "10.142.0.0/20",
}

# Service endpoint mappings for Azure subnets
_SERVICE_ENDPOINT_MAP = {
    "database": [
        "Microsoft.Sql",
        "Microsoft.Storage",
    ],
    "private": [
        "Microsoft.Storage",
        "Microsoft.KeyVault",
    ],
    "public": [],
}

# Delegation mappings for database subnets
_DELEGATION_MAP = {
    "postgresql": "Microsoft.DBforPostgreSQL/flexibleServers",
    "postgres": "Microsoft.DBforPostgreSQL/flexibleServers",
    "mysql": "Microsoft.DBforMySQL/flexibleServers",
    "sql": None,  # Azure SQL uses private endpoints, not delegation
}


# ─────────────────────────────────────────────────────────────
# CIDR Utilities
# ─────────────────────────────────────────────────────────────

def validate_cidr(cidr: str) -> ipaddress.IPv4Network:
    """Parse and validate a CIDR block. Raises ValueError on invalid input."""
    return ipaddress.IPv4Network(cidr, strict=False)


def subnets_overlap(a: str, b: str) -> bool:
    """Return True if two CIDR blocks overlap."""
    net_a = ipaddress.IPv4Network(a, strict=False)
    net_b = ipaddress.IPv4Network(b, strict=False)
    return net_a.overlaps(net_b)


def plan_subnets(
    vnet_cidr: str,
    count: int,
    prefix_len: int = DEFAULT_SUBNET_PREFIX,
) -> List[str]:
    """Divide a VNet CIDR into ``count`` non-overlapping subnets.

    Returns a list of CIDR strings. Raises ValueError if the request
    cannot be fulfilled (too many subnets for the address space).
    """
    network = validate_cidr(vnet_cidr)
    if prefix_len <= network.prefixlen:
        raise ValueError(
            f"Subnet prefix /{prefix_len} must be longer than VNet prefix /{network.prefixlen}"
        )

    all_subnets = list(network.subnets(new_prefix=prefix_len))
    if count > len(all_subnets):
        raise ValueError(
            f"Cannot create {count} /{prefix_len} subnets in {vnet_cidr} "
            f"(max {len(all_subnets)})"
        )
    return [str(s) for s in all_subnets[:count]]


def validate_no_overlaps(cidrs: List[str]) -> List[str]:
    """Check a list of CIDRs for overlaps. Returns list of warning strings."""
    warnings: List[str] = []
    nets = [(c, ipaddress.IPv4Network(c, strict=False)) for c in cidrs]
    for i in range(len(nets)):
        for j in range(i + 1, len(nets)):
            if nets[i][1].overlaps(nets[j][1]):
                warnings.append(f"CIDR overlap: {nets[i][0]} overlaps with {nets[j][0]}")
    return warnings


# ─────────────────────────────────────────────────────────────
# Security Group → NSG Translation
# ─────────────────────────────────────────────────────────────

def _normalize_protocol(proto: str) -> str:
    """Normalize AWS/GCP protocol to Azure protocol name."""
    return _AWS_PROTOCOL_MAP.get(str(proto).lower().strip(), "Tcp")


def _port_range_str(from_port: Any, to_port: Any) -> str:
    """Convert port range to Azure format."""
    fp = int(from_port) if from_port not in (None, "", -1, "-1") else 0
    tp = int(to_port) if to_port not in (None, "", -1, "-1") else 65535

    if fp == 0 and tp == 65535:
        return "*"
    if fp == tp:
        return str(fp)
    return f"{fp}-{tp}"


def _port_rule_name(port_str: str, direction: str) -> str:
    """Generate a human-readable rule name from port specification."""
    label = _PORT_NAMES.get(port_str, f"Port-{port_str}")
    if port_str == "*":
        label = "AllPorts"
    elif "-" in port_str:
        label = f"Range-{port_str.replace('-', 'to')}"
    return f"{direction}-{label}"


def _normalize_cidr_source(source: str) -> str:
    """Normalize source address — handle AWS special CIDRs."""
    if not source or source in ("0.0.0.0/0", "::/0"):
        return "*"
    # AWS security group IDs can't be mapped directly
    if source.startswith("sg-"):
        return "*"  # Will generate a warning
    return source


def translate_security_group(
    sg: dict,
    base_priority: int = 100,
    nsg_name: Optional[str] = None,
) -> NSGSpec:
    """Translate an AWS Security Group or GCP firewall rule set to Azure NSG.

    Args:
        sg: Dict with 'name', 'inbound_rules', 'outbound_rules'.
            Each rule: { protocol, from_port, to_port, source/cidr, description }
        base_priority: Starting priority (Azure NSGs need 100-4096).
        nsg_name: Override NSG name.
    """
    name = nsg_name or f"nsg-{_sanitize_name(sg.get('name', 'default'))}"
    rules: List[NSGRule] = []
    priority = base_priority

    for rule in sg.get("inbound_rules", []):
        if priority > 4096:
            break
        proto = _normalize_protocol(rule.get("protocol", "tcp"))
        dest_port = _port_range_str(rule.get("from_port"), rule.get("to_port"))
        src = _normalize_cidr_source(rule.get("source", rule.get("cidr", "0.0.0.0/0")))
        rule_name = _port_rule_name(dest_port, "Allow-Inbound")

        # Deduplicate names
        existing_names = {r.name for r in rules}
        if rule_name in existing_names:
            rule_name = f"{rule_name}-{priority}"

        rules.append(NSGRule(
            name=rule_name,
            priority=priority,
            direction="Inbound",
            access="Allow",
            protocol=proto,
            source_address=src,
            source_port="*",
            destination_address="*",
            destination_port=dest_port,
            description=rule.get("description", ""),
        ))
        priority += 10

    for rule in sg.get("outbound_rules", []):
        if priority > 4096:
            break
        proto = _normalize_protocol(rule.get("protocol", "tcp"))
        dest_port = _port_range_str(rule.get("from_port"), rule.get("to_port"))
        dest = _normalize_cidr_source(rule.get("destination", rule.get("cidr", "0.0.0.0/0")))
        rule_name = _port_rule_name(dest_port, "Allow-Outbound")

        existing_names = {r.name for r in rules}
        if rule_name in existing_names:
            rule_name = f"{rule_name}-{priority}"

        rules.append(NSGRule(
            name=rule_name,
            priority=priority,
            direction="Outbound",
            access="Allow",
            protocol=proto,
            source_address="*",
            source_port="*",
            destination_address=dest,
            destination_port=dest_port,
            description=rule.get("description", ""),
        ))
        priority += 10

    return NSGSpec(name=name, rules=rules)


# ─────────────────────────────────────────────────────────────
# Route Table Translation
# ─────────────────────────────────────────────────────────────

def translate_route_table(rt: dict, rt_name: Optional[str] = None) -> RouteTableSpec:
    """Translate an AWS route table to Azure route table.

    Args:
        rt: Dict with 'name', 'routes'. Each route:
            { destination_cidr, target_type, target_id }
            target_type: 'igw' | 'nat' | 'vpn' | 'pcx' | 'local' | 'tgw'
    """
    name = rt_name or f"rt-{_sanitize_name(rt.get('name', 'main'))}"
    routes: List[RouteSpec] = []

    for route in rt.get("routes", []):
        dest = route.get("destination_cidr", "0.0.0.0/0")
        target_type = str(route.get("target_type", "")).lower()
        target_id = route.get("target_id", "")

        if target_type in ("local", "vpclocal"):
            # VNet-local route — Azure handles this implicitly
            continue

        if target_type in ("igw", "internet-gateway", "internet"):
            routes.append(RouteSpec(
                name=f"route-internet-{len(routes)}",
                address_prefix=dest,
                next_hop_type="Internet",
            ))
        elif target_type in ("nat", "nat-gateway"):
            # Azure NAT Gateway doesn't use route tables — handled via subnet association
            # But if explicit routing is desired:
            routes.append(RouteSpec(
                name=f"route-nat-{len(routes)}",
                address_prefix=dest,
                next_hop_type="VirtualAppliance",
                next_hop_address=target_id if target_id else None,
            ))
        elif target_type in ("vpn", "vpn-gateway", "vgw"):
            routes.append(RouteSpec(
                name=f"route-vpn-{len(routes)}",
                address_prefix=dest,
                next_hop_type="VirtualNetworkGateway",
            ))
        elif target_type in ("pcx", "peering", "vnet-peering"):
            routes.append(RouteSpec(
                name=f"route-peering-{len(routes)}",
                address_prefix=dest,
                next_hop_type="VnetLocal",
            ))
        elif target_type in ("tgw", "transit-gateway"):
            # Transit Gateway → Virtual WAN or Virtual Network Gateway
            routes.append(RouteSpec(
                name=f"route-transit-{len(routes)}",
                address_prefix=dest,
                next_hop_type="VirtualNetworkGateway",
            ))
        elif target_type in ("blackhole", "none"):
            routes.append(RouteSpec(
                name=f"route-blackhole-{len(routes)}",
                address_prefix=dest,
                next_hop_type="None",
            ))
        else:
            # Fallback — generic virtual appliance
            routes.append(RouteSpec(
                name=f"route-custom-{len(routes)}",
                address_prefix=dest,
                next_hop_type="VirtualAppliance",
                next_hop_address=target_id if target_id else None,
            ))

    return RouteTableSpec(name=name, routes=routes)


# ─────────────────────────────────────────────────────────────
# Topology Detection
# ─────────────────────────────────────────────────────────────

def _detect_topology(analysis: dict) -> str:
    """Detect network topology type from analysis result.

    Heuristics:
      - hub-spoke: Transit Gateway / Virtual WAN / multiple VPCs with peering
      - mesh: multiple peering connections between VPCs
      - flat: single VPC / simple architecture
    """
    text = str(analysis).lower()

    hub_indicators = (
        "transit gateway", "transit_gateway", "tgw",
        "virtual wan", "hub-spoke", "hub_spoke", "hub and spoke",
        "shared services", "central hub",
    )
    mesh_indicators = (
        "mesh", "full mesh", "vpc peering", "vnet peering",
        "multiple vpc", "multi-vpc",
    )

    hub_score = sum(1 for h in hub_indicators if h in text)
    mesh_score = sum(1 for m in mesh_indicators if m in text)

    if hub_score >= 2:
        return "hub-spoke"
    if mesh_score >= 2:
        return "mesh"
    return "flat"


# ─────────────────────────────────────────────────────────────
# Subnet Zone Classification
# ─────────────────────────────────────────────────────────────

def _classify_subnet_zone(subnet: dict) -> str:
    """Classify a subnet as public, private, or database.

    Uses naming conventions, route table targets, and tags.
    """
    name = str(subnet.get("name", "")).lower()
    tags = str(subnet.get("tags", "")).lower()
    combined = f"{name} {tags}"

    if any(k in combined for k in ("public", "web", "dmz", "bastion", "frontend")):
        return "public"
    if any(k in combined for k in ("database", "db", "rds", "data", "sql", "postgres", "mysql")):
        return "database"
    return "private"


def _infer_db_type(subnet: dict) -> Optional[str]:
    """Attempt to infer database type from subnet metadata."""
    combined = str(subnet).lower()
    if "postgres" in combined or "postgresql" in combined:
        return "postgresql"
    if "mysql" in combined:
        return "mysql"
    if "sql" in combined or "rds" in combined:
        return "postgresql"  # default to PostgreSQL
    return None


# ─────────────────────────────────────────────────────────────
# Resource Name Sanitization
# ─────────────────────────────────────────────────────────────

_NAME_RE = re.compile(r"[^a-zA-Z0-9-]")


def _sanitize_name(name: str) -> str:
    """Sanitize a resource name for Azure (alphanumeric + hyphens only)."""
    sanitized = _NAME_RE.sub("-", name.strip())
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    return sanitized[:63] or "default"


# ─────────────────────────────────────────────────────────────
# Main Translation Engine
# ─────────────────────────────────────────────────────────────

_lock = threading.Lock()


def translate_network_topology(
    analysis: dict,
    vnet_cidr: str = DEFAULT_VNET_CIDR,
    subnet_prefix: int = DEFAULT_SUBNET_PREFIX,
    vnet_name: Optional[str] = None,
) -> NetworkTopology:
    """Translate detected network topology from analysis result to Azure VNet.

    Thread-safe. Extracts networking data from the analysis dict produced by
    the vision/analysis pipeline and generates a complete Azure network plan.

    Args:
        analysis: Full analysis result dict (from diagram analysis).
        vnet_cidr: VNet address space (default 10.0.0.0/16).
        subnet_prefix: Default subnet prefix length (default /24).
        vnet_name: Override VNet name.

    Returns:
        NetworkTopology with all translated components.
    """
    validate_cidr(vnet_cidr)
    provider = normalize_source_provider(analysis.get("source_provider"))

    with _lock:
        return _translate_impl(analysis, vnet_cidr, subnet_prefix, vnet_name, provider)


def _translate_impl(
    analysis: dict,
    vnet_cidr: str,
    subnet_prefix: int,
    vnet_name: Optional[str],
    provider: str,
) -> NetworkTopology:
    """Internal implementation — called under lock."""
    warnings: List[str] = []
    topology_type = _detect_topology(analysis)

    # ── Extract network data from analysis ──
    network_data = _extract_network_data(analysis, provider)

    # ── VNet name ──
    final_vnet_name = vnet_name or f"vnet-{_sanitize_name(network_data.get('vpc_name', 'main'))}"

    # ── Plan subnets ──
    source_subnets = network_data.get("subnets", [])
    if not source_subnets:
        # Default: 3 subnets (public, private, database)
        source_subnets = [
            {"name": "public", "zone_type": "public"},
            {"name": "private", "zone_type": "private"},
            {"name": "database", "zone_type": "database"},
        ]
        warnings.append("No subnets detected — generated default 3-tier layout (public/private/database)")

    subnet_count = len(source_subnets)
    try:
        cidr_blocks = plan_subnets(vnet_cidr, subnet_count, subnet_prefix)
    except ValueError as exc:
        warnings.append(str(exc))
        cidr_blocks = plan_subnets(vnet_cidr, subnet_count, subnet_prefix + 2)

    # ── Build subnet specs ──
    subnets: List[SubnetSpec] = []
    public_subnets: List[str] = []
    private_subnets: List[str] = []

    for i, src_sub in enumerate(source_subnets):
        zone_type = src_sub.get("zone_type") or _classify_subnet_zone(src_sub)
        sub_name = f"snet-{_sanitize_name(src_sub.get('name', f'subnet-{i}'))}"
        cidr = cidr_blocks[i] if i < len(cidr_blocks) else cidr_blocks[-1]

        # Service endpoints and delegation
        endpoints = list(_SERVICE_ENDPOINT_MAP.get(zone_type, []))
        delegation = None
        if zone_type == "database":
            db_type = _infer_db_type(src_sub)
            if db_type:
                delegation = _DELEGATION_MAP.get(db_type)

        nsg_name = f"nsg-{_sanitize_name(src_sub.get('name', f'subnet-{i}'))}"

        spec = SubnetSpec(
            name=sub_name,
            cidr=cidr,
            zone_type=zone_type,
            availability_zone=src_sub.get("availability_zone", ""),
            service_endpoints=endpoints,
            delegation=delegation,
            nat_gateway=zone_type == "private",
            nsg_name=nsg_name,
        )
        subnets.append(spec)

        if zone_type == "public":
            public_subnets.append(sub_name)
        elif zone_type == "private":
            private_subnets.append(sub_name)

    # ── CIDR overlap validation ──
    overlap_warnings = validate_no_overlaps([s.cidr for s in subnets])
    warnings.extend(overlap_warnings)

    # ── NSGs ──
    nsgs: List[NSGSpec] = []
    source_sgs = network_data.get("security_groups", [])
    if source_sgs:
        for sg in source_sgs:
            nsgs.append(translate_security_group(sg))
    else:
        # Generate default NSGs per subnet type
        nsgs.extend(_default_nsgs(subnets))
        if not source_sgs:
            warnings.append("No security groups detected — generated default NSG rules")

    # ── Route tables ──
    route_tables: List[RouteTableSpec] = []
    source_rts = network_data.get("route_tables", [])
    if source_rts:
        for rt in source_rts:
            route_tables.append(translate_route_table(rt))
    else:
        route_tables = _default_route_tables(subnets)

    # ── NAT Gateway ──
    nat_gw = None
    nat_subnets = [s.name for s in subnets if s.nat_gateway]
    if nat_subnets:
        nat_gw = NATGatewaySpec(
            name=f"natgw-{_sanitize_name(final_vnet_name)}",
            public_ip_name=f"pip-natgw-{_sanitize_name(final_vnet_name)}",
            associated_subnets=nat_subnets,
        )

    return NetworkTopology(
        vnet_name=final_vnet_name,
        vnet_cidr=vnet_cidr,
        subnets=subnets,
        nsgs=nsgs,
        route_tables=route_tables,
        nat_gateway=nat_gw,
        topology_type=topology_type,
        source_provider=provider,
        warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────
# Network Data Extraction
# ─────────────────────────────────────────────────────────────

def _extract_network_data(analysis: dict, provider: str) -> dict:
    """Extract networking-relevant data from an analysis result.

    Looks for:
      - Explicit 'network' or 'networking' keys
      - VPC/VNet mentions in mappings
      - Subnet mentions in service descriptions
      - Security group / firewall rule mentions
    """
    # Direct network section
    network = analysis.get("network") or analysis.get("networking") or {}
    if isinstance(network, dict) and network:
        return network

    # Build from analysis mappings and metadata
    result: Dict[str, Any] = {
        "vpc_name": "main",
        "subnets": [],
        "security_groups": [],
        "route_tables": [],
    }

    mappings = analysis.get("mappings", [])
    detected_subnets: List[dict] = []
    detected_sgs: List[dict] = []

    for m in mappings:
        source = m.get("source_service", "")
        if isinstance(source, dict):
            source = source.get("name", "")
        source_lower = source.lower()
        category = m.get("category", "").lower()
        role = str(m.get("role", m.get("description", ""))).lower()

        # Detect VPC name
        if "vpc" in source_lower or (category == "networking" and "virtual" in source_lower):
            result["vpc_name"] = source

        # Detect subnets
        if "subnet" in source_lower or "subnet" in role:
            zone_type = _classify_subnet_zone({"name": source, "tags": role})
            detected_subnets.append({
                "name": source,
                "zone_type": zone_type,
            })

        # Detect security constructs
        if any(k in source_lower for k in ("security group", "sg", "firewall", "nacl")):
            detected_sgs.append({
                "name": source,
                "inbound_rules": _infer_default_sg_rules(role, "inbound"),
                "outbound_rules": _infer_default_sg_rules(role, "outbound"),
            })

    result["subnets"] = detected_subnets
    result["security_groups"] = detected_sgs
    return result


def _infer_default_sg_rules(role_text: str, direction: str) -> List[dict]:
    """Infer security group rules from role descriptions."""
    rules: List[dict] = []
    role = role_text.lower()

    if direction == "inbound":
        if any(k in role for k in ("web", "http", "frontend", "public", "load balancer", "lb")):
            rules.append({"protocol": "tcp", "from_port": 80, "to_port": 80, "source": "0.0.0.0/0", "description": "HTTP"})
            rules.append({"protocol": "tcp", "from_port": 443, "to_port": 443, "source": "0.0.0.0/0", "description": "HTTPS"})
        if any(k in role for k in ("ssh", "bastion", "management")):
            rules.append({"protocol": "tcp", "from_port": 22, "to_port": 22, "source": "0.0.0.0/0", "description": "SSH"})
        if any(k in role for k in ("database", "db", "rds", "postgres", "mysql")):
            rules.append({"protocol": "tcp", "from_port": 5432, "to_port": 5432, "source": "10.0.0.0/16", "description": "PostgreSQL"})
        if any(k in role for k in ("redis", "cache", "elasticache")):
            rules.append({"protocol": "tcp", "from_port": 6379, "to_port": 6379, "source": "10.0.0.0/16", "description": "Redis"})
    elif direction == "outbound":
        # Default: allow all outbound
        rules.append({"protocol": "-1", "from_port": -1, "to_port": -1, "destination": "0.0.0.0/0", "description": "All outbound"})

    return rules


# ─────────────────────────────────────────────────────────────
# Default NSG / Route Table Generation
# ─────────────────────────────────────────────────────────────

def _default_nsgs(subnets: List[SubnetSpec]) -> List[NSGSpec]:
    """Generate default NSGs based on subnet zone types."""
    nsgs: List[NSGSpec] = []
    for subnet in subnets:
        rules: List[NSGRule] = []
        priority = 100

        if subnet.zone_type == "public":
            rules.extend([
                NSGRule("Allow-Inbound-HTTP", priority, "Inbound", "Allow", "Tcp",
                        "*", "*", "*", "80", "Allow HTTP from internet"),
                NSGRule("Allow-Inbound-HTTPS", priority + 10, "Inbound", "Allow", "Tcp",
                        "*", "*", "*", "443", "Allow HTTPS from internet"),
                NSGRule("Deny-Inbound-All", 4096, "Inbound", "Deny", "*",
                        "*", "*", "*", "*", "Deny all other inbound"),
            ])
        elif subnet.zone_type == "private":
            rules.extend([
                NSGRule("Allow-Inbound-VNet", priority, "Inbound", "Allow", "*",
                        "VirtualNetwork", "*", "VirtualNetwork", "*", "Allow VNet traffic"),
                NSGRule("Allow-Inbound-LB", priority + 10, "Inbound", "Allow", "*",
                        "AzureLoadBalancer", "*", "*", "*", "Allow LB probes"),
                NSGRule("Deny-Inbound-All", 4096, "Inbound", "Deny", "*",
                        "*", "*", "*", "*", "Deny all other inbound"),
            ])
        elif subnet.zone_type == "database":
            rules.extend([
                NSGRule("Allow-Inbound-PrivateSubnet", priority, "Inbound", "Allow", "Tcp",
                        "VirtualNetwork", "*", "*", "5432", "Allow PostgreSQL from VNet"),
                NSGRule("Allow-Inbound-PrivateSubnet-MySQL", priority + 10, "Inbound", "Allow", "Tcp",
                        "VirtualNetwork", "*", "*", "3306", "Allow MySQL from VNet"),
                NSGRule("Deny-Inbound-All", 4096, "Inbound", "Deny", "*",
                        "*", "*", "*", "*", "Deny all other inbound"),
            ])

        # Common outbound rules
        rules.append(
            NSGRule("Allow-Outbound-All", 100, "Outbound", "Allow", "*",
                    "*", "*", "*", "*", "Allow all outbound")
        )

        nsg_name = subnet.nsg_name or f"nsg-{subnet.name}"
        nsgs.append(NSGSpec(name=nsg_name, rules=rules))
    return nsgs


def _default_route_tables(subnets: List[SubnetSpec]) -> List[RouteTableSpec]:
    """Generate default route tables based on subnet types."""
    tables: List[RouteTableSpec] = []

    public_subs = [s.name for s in subnets if s.zone_type == "public"]
    private_subs = [s.name for s in subnets if s.zone_type == "private"]
    db_subs = [s.name for s in subnets if s.zone_type == "database"]

    if public_subs:
        tables.append(RouteTableSpec(
            name="rt-public",
            routes=[
                RouteSpec("route-internet", "0.0.0.0/0", "Internet"),
            ],
            associated_subnets=public_subs,
        ))

    if private_subs:
        tables.append(RouteTableSpec(
            name="rt-private",
            routes=[],  # NAT Gateway is associated to subnet, not via routes in Azure
            associated_subnets=private_subs,
        ))

    if db_subs:
        tables.append(RouteTableSpec(
            name="rt-database",
            routes=[],  # Database subnets — no internet route
            associated_subnets=db_subs,
        ))

    return tables


# ─────────────────────────────────────────────────────────────
# GCP-Specific Translation
# ─────────────────────────────────────────────────────────────

def translate_gcp_firewall_rule(rule: dict, base_priority: int = 100) -> NSGRule:
    """Translate a single GCP firewall rule to Azure NSG rule.

    GCP rule format:
        { name, direction (INGRESS/EGRESS), allowed/denied: [{protocol, ports}],
          sourceRanges/destinationRanges, priority }
    """
    direction = "Inbound" if rule.get("direction", "INGRESS") == "INGRESS" else "Outbound"
    gcp_priority = rule.get("priority", 1000)
    # GCP priority 0-65535 → Azure 100-4096 (linear map)
    azure_priority = max(100, min(4096, int(gcp_priority * 4096 / 65535)))

    allowed = rule.get("allowed", [])
    denied = rule.get("denied", [])
    access = "Allow" if allowed else "Deny"
    proto_list = allowed or denied

    protocol = "*"
    dest_port = "*"
    if proto_list:
        first = proto_list[0]
        protocol = _normalize_protocol(first.get("IPProtocol", first.get("protocol", "all")))
        ports = first.get("ports", [])
        if ports:
            dest_port = str(ports[0])
            if len(ports) > 1:
                dest_port = f"{ports[0]}-{ports[-1]}"

    source = "*"
    if direction == "Inbound":
        ranges = rule.get("sourceRanges", [])
        source = ranges[0] if ranges else "*"
    dest = "*"
    if direction == "Outbound":
        ranges = rule.get("destinationRanges", [])
        dest = ranges[0] if ranges else "*"

    return NSGRule(
        name=f"{direction}-{_sanitize_name(rule.get('name', 'rule'))}",
        priority=azure_priority,
        direction=direction,
        access=access,
        protocol=protocol,
        source_address=source if direction == "Inbound" else "*",
        source_port="*",
        destination_address=dest if direction == "Outbound" else "*",
        destination_port=dest_port,
        description=rule.get("description", ""),
    )


def translate_gcp_network(
    network: dict,
    vnet_cidr: str = DEFAULT_VNET_CIDR,
    subnet_prefix: int = DEFAULT_SUBNET_PREFIX,
    vnet_name: Optional[str] = None,
) -> NetworkTopology:
    """Translate a GCP VPC network to Azure VNet.

    Handles auto-mode (predefined CIDRs per region) and custom-mode VPCs.
    """
    mode = network.get("autoCreateSubnetworks", network.get("mode", "custom"))
    is_auto = mode is True or str(mode).lower() == "auto"
    vpc_name = network.get("name", "default")

    warnings: List[str] = []
    subnets_data: List[dict] = []

    if is_auto:
        warnings.append(
            "GCP auto-mode VPC detected — mapping predefined regional subnets to Azure"
        )
        for region, cidr in _GCP_AUTO_MODE_CIDRS.items():
            subnets_data.append({
                "name": f"subnet-{region}",
                "zone_type": "private",
                "availability_zone": region,
            })

    custom_subnets = network.get("subnetworks", network.get("subnets", []))
    for sub in custom_subnets:
        subnets_data.append({
            "name": sub.get("name", "subnet"),
            "zone_type": _classify_subnet_zone(sub),
            "availability_zone": sub.get("region", ""),
        })

    # Build a synthetic analysis for reuse
    analysis = {
        "source_provider": "gcp",
        "network": {
            "vpc_name": vpc_name,
            "subnets": subnets_data or [
                {"name": "public", "zone_type": "public"},
                {"name": "private", "zone_type": "private"},
                {"name": "database", "zone_type": "database"},
            ],
            "security_groups": [],
            "route_tables": [],
        },
    }

    # Translate firewall rules → NSGs
    gcp_firewalls = network.get("firewallRules", network.get("firewall_rules", []))
    sg_groups: Dict[str, dict] = {}
    for fw in gcp_firewalls:
        direction = fw.get("direction", "INGRESS")
        nsg_rule = translate_gcp_firewall_rule(fw)
        # Group by target network
        group_name = fw.get("network", "default")
        if group_name not in sg_groups:
            sg_groups[group_name] = {"name": group_name, "inbound_rules": [], "outbound_rules": []}
        if direction == "INGRESS":
            sg_groups[group_name]["inbound_rules"].append({
                "protocol": nsg_rule.protocol,
                "from_port": nsg_rule.destination_port,
                "to_port": nsg_rule.destination_port,
                "source": nsg_rule.source_address,
                "description": nsg_rule.description,
            })
        else:
            sg_groups[group_name]["outbound_rules"].append({
                "protocol": nsg_rule.protocol,
                "from_port": nsg_rule.destination_port,
                "to_port": nsg_rule.destination_port,
                "destination": nsg_rule.destination_address,
                "description": nsg_rule.description,
            })

    analysis["network"]["security_groups"] = list(sg_groups.values())

    # Cloud Router → Route Server (note in warnings)
    if network.get("routerConfig") or network.get("cloud_router"):
        warnings.append("GCP Cloud Router detected — consider Azure Route Server for dynamic routing")

    topo = translate_network_topology(analysis, vnet_cidr, subnet_prefix, vnet_name)
    topo.warnings.extend(warnings)
    return topo
