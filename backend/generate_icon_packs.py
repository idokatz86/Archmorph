#!/usr/bin/env python3
"""Generate SVG icon packs for all Azure, AWS, and GCP services.

Reads the service catalogs from the Archmorph codebase and generates:
- One SVG icon per service (category-coloured, with abbreviated label)
- A metadata.json manifest for each provider

Usage:
    cd backend && python generate_icon_packs.py
"""

from __future__ import annotations

import json
import os
import re
import html

# ─── Provider colour palettes ────────────────────────────────
# Each category maps to (fill, stroke, accent)

AZURE_PALETTE = {
    "Compute":     ("#0078D4", "#005A9E", "#50E6FF"),
    "Storage":     ("#0078D4", "#005A9E", "#773ADC"),
    "Database":    ("#0078D4", "#005A9E", "#E3008C"),
    "Networking":  ("#0078D4", "#005A9E", "#00B7C3"),
    "Security":    ("#E81123", "#A80000", "#FFB900"),
    "AI/ML":       ("#773ADC", "#5C2D91", "#50E6FF"),
    "Analytics":   ("#0078D4", "#005A9E", "#FFB900"),
    "Integration": ("#00B7C3", "#008575", "#50E6FF"),
    "DevTools":    ("#0078D4", "#005A9E", "#68217A"),
    "Management":  ("#0078D4", "#005A9E", "#7FBA00"),
    "IoT":         ("#00B7C3", "#008575", "#FF8C00"),
    "Media":       ("#E3008C", "#9B0062", "#50E6FF"),
    "Migration":   ("#0078D4", "#005A9E", "#FFB900"),
    "Business":    ("#0078D4", "#005A9E", "#107C10"),
}

AWS_PALETTE = {
    "Compute":     ("#FF9900", "#CC7A00", "#232F3E"),
    "Storage":     ("#3F8624", "#2E6B1A", "#232F3E"),
    "Database":    ("#3B48CC", "#2D3A9E", "#232F3E"),
    "Networking":  ("#8C4FFF", "#6B33CC", "#232F3E"),
    "Security":    ("#DD344C", "#B02A3D", "#232F3E"),
    "AI/ML":       ("#01A88D", "#018070", "#232F3E"),
    "Analytics":   ("#8C4FFF", "#6B33CC", "#232F3E"),
    "Integration": ("#E7157B", "#B81163", "#232F3E"),
    "DevTools":    ("#3B48CC", "#2D3A9E", "#232F3E"),
    "Management":  ("#E7157B", "#B81163", "#232F3E"),
    "Containers":  ("#FF9900", "#CC7A00", "#232F3E"),
    "IoT":         ("#01A88D", "#018070", "#232F3E"),
    "Media":       ("#FF9900", "#CC7A00", "#232F3E"),
    "Migration":   ("#01A88D", "#018070", "#232F3E"),
    "Business":    ("#E7157B", "#B81163", "#232F3E"),
}

GCP_PALETTE = {
    "Compute":     ("#4285F4", "#3367D6", "#FFFFFF"),
    "Storage":     ("#4285F4", "#3367D6", "#FFFFFF"),
    "Database":    ("#4285F4", "#3367D6", "#FFFFFF"),
    "Networking":  ("#4285F4", "#3367D6", "#FFFFFF"),
    "Security":    ("#EA4335", "#D33426", "#FFFFFF"),
    "AI/ML":       ("#4285F4", "#3367D6", "#FBBC04"),
    "Analytics":   ("#4285F4", "#3367D6", "#34A853"),
    "Integration": ("#EA4335", "#D33426", "#FFFFFF"),
    "DevTools":    ("#4285F4", "#3367D6", "#FFFFFF"),
    "Management":  ("#34A853", "#2D8E47", "#FFFFFF"),
    "IoT":         ("#4285F4", "#3367D6", "#FBBC04"),
    "Media":       ("#EA4335", "#D33426", "#FFFFFF"),
    "Migration":   ("#4285F4", "#3367D6", "#FFFFFF"),
    "Business":    ("#34A853", "#2D8E47", "#FFFFFF"),
}

PALETTES = {
    "azure": AZURE_PALETTE,
    "aws":   AWS_PALETTE,
    "gcp":   GCP_PALETTE,
}

# ─── Category shapes ─────────────────────────────────────────
# Each category produces a different SVG shape background

CATEGORY_SHAPES = {
    "Compute":     "hexagon",
    "Storage":     "cylinder",
    "Database":    "cylinder",
    "Networking":  "diamond",
    "Security":    "shield",
    "AI/ML":       "brain",
    "Analytics":   "chart",
    "Integration": "arrows",
    "DevTools":    "gear",
    "Management":  "sliders",
    "Containers":  "hexagon",
    "IoT":         "circle",
    "Media":       "play",
    "Migration":   "arrows",
    "Business":    "building",
}


def _abbreviate(name: str, max_len: int = 12) -> str:
    """Create a short label for the icon."""
    # Well-known abbreviations
    abbrevs = {
        "Virtual Machines": "VM",
        "Azure Functions": "Func",
        "Container Instances": "ACI",
        "Container Apps": "ACA",
        "App Service": "App Svc",
        "VM Scale Sets": "VMSS",
        "Blob Storage": "Blob",
        "Managed Disks": "Disk",
        "Azure Files": "Files",
        "SQL Database": "SQL DB",
        "SQL Managed Instance": "SQL MI",
        "Cosmos DB": "Cosmos",
        "Cache for Redis": "Redis",
        "Synapse Analytics": "Synapse",
        "Virtual Network": "VNet",
        "API Management": "APIM",
        "Load Balancer": "LB",
        "Application Gateway": "App GW",
        "ExpressRoute": "ER",
        "Front Door": "FD",
        "Virtual WAN": "vWAN",
        "Azure Firewall": "FW",
        "Traffic Manager": "TM",
        "Key Vault": "KV",
        "Azure Monitor": "Monitor",
        "Application Insights": "AppIns",
        "Container Registry": "ACR",
        "Service Bus": "Svc Bus",
        "Event Grid": "EvGrid",
        "Logic Apps": "Logic",
        "Azure DevOps": "DevOps",
        "Resource Manager": "ARM",
        "Cost Management": "Cost",
        "Machine Learning": "ML",
        "Azure OpenAI Service": "OpenAI",
        "IoT Hub": "IoT Hub",
        "IoT Edge": "IoT Edge",
        "Azure Databricks": "DBricks",
        "Azure Kubernetes Service": "AKS",
        # AWS
        "EC2 Instance": "EC2",
        "EC2": "EC2",
        "Lambda": "Lambda",
        "Lambda Function": "Lambda",
        "S3": "S3",
        "S3 Bucket": "S3",
        "Elastic Beanstalk": "EB",
        "CloudFront": "CF",
        "Route 53": "R53",
        "API Gateway": "API GW",
        "DynamoDB": "DDB",
        "ElastiCache": "ECache",
        "CloudWatch": "CWatch",
        "CloudFormation": "CFN",
        "CodePipeline": "CPipe",
        "SageMaker": "SM",
        "Step Functions": "StepFn",
        "EventBridge": "EvBrdg",
        "Secrets Manager": "Secrets",
        "Certificate Manager": "CertMgr",
        "Systems Manager": "SysMgr",
        "Elastic Load Balancing": "ELB",
        "ELB": "ELB",
        "Direct Connect": "DX",
        "Global Accelerator": "GA",
        "Transit Gateway": "TGW",
        "Network Firewall": "NetFW",
        # GCP
        "Compute Engine": "GCE",
        "Cloud Functions": "GCFn",
        "Cloud Run": "Run",
        "App Engine": "GAE",
        "Cloud Storage": "GCS",
        "Cloud SQL": "SQL",
        "Cloud Spanner": "Spanner",
        "Cloud Load Balancing": "GLB",
        "Cloud Interconnect": "IC",
        "Cloud VPN": "VPN",
        "Cloud NAT": "NAT",
        "Cloud Armor": "Armor",
        "Cloud IAM": "IAM",
        "Secret Manager": "Secrets",
        "Security Command Center": "SCC",
        "Vertex AI": "Vertex",
        "Cloud Build": "Build",
        "Cloud Deploy": "Deploy",
        "Artifact Registry": "AR",
        "Cloud Monitoring": "Monitor",
        "Cloud Logging": "Logging",
        "Google Kubernetes Engine": "GKE",
    }
    if name in abbrevs:
        return abbrevs[name]
    # Auto-abbreviate: take initials of words if too long
    if len(name) <= max_len:
        return name
    # Try removing common prefixes
    for prefix in ("Azure ", "AWS ", "Google ", "Cloud ", "Amazon "):
        if name.startswith(prefix):
            short = name[len(prefix):]
            if len(short) <= max_len:
                return short
    # Initials
    words = name.split()
    if len(words) >= 2:
        initials = "".join(w[0].upper() for w in words if w[0].isalpha())
        if len(initials) <= max_len:
            return initials
    return name[:max_len]


def _shape_svg(shape: str, fill: str, stroke: str, accent: str, label: str) -> str:
    """Generate a 64x64 SVG icon with a category-specific background shape."""
    safe_label = html.escape(label)
    font_size = 10
    if len(label) > 8:
        font_size = 8
    if len(label) > 10:
        font_size = 7
    if len(label) > 12:
        font_size = 6

    header = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
    footer = '</svg>'

    shapes = {
        "hexagon": f'''
  <polygon points="32,4 56,18 56,46 32,60 8,46 8,18" fill="{fill}" stroke="{stroke}" stroke-width="2"/>
  <text x="32" y="35" text-anchor="middle" fill="white" font-size="{font_size}" font-family="Segoe UI,sans-serif" font-weight="600">{safe_label}</text>''',

        "cylinder": f'''
  <ellipse cx="32" cy="16" rx="22" ry="8" fill="{accent}" opacity="0.3"/>
  <rect x="10" y="16" width="44" height="32" fill="{fill}"/>
  <ellipse cx="32" cy="16" rx="22" ry="8" fill="{fill}" stroke="{stroke}" stroke-width="2"/>
  <ellipse cx="32" cy="48" rx="22" ry="8" fill="{fill}" stroke="{stroke}" stroke-width="2"/>
  <line x1="10" y1="16" x2="10" y2="48" stroke="{stroke}" stroke-width="2"/>
  <line x1="54" y1="16" x2="54" y2="48" stroke="{stroke}" stroke-width="2"/>
  <text x="32" y="36" text-anchor="middle" fill="white" font-size="{font_size}" font-family="Segoe UI,sans-serif" font-weight="600">{safe_label}</text>''',

        "diamond": f'''
  <polygon points="32,4 60,32 32,60 4,32" fill="{fill}" stroke="{stroke}" stroke-width="2"/>
  <text x="32" y="35" text-anchor="middle" fill="white" font-size="{font_size}" font-family="Segoe UI,sans-serif" font-weight="600">{safe_label}</text>''',

        "shield": f'''
  <path d="M32 4 L56 16 L56 36 Q56 56 32 60 Q8 56 8 36 L8 16 Z" fill="{fill}" stroke="{stroke}" stroke-width="2"/>
  <text x="32" y="38" text-anchor="middle" fill="white" font-size="{font_size}" font-family="Segoe UI,sans-serif" font-weight="600">{safe_label}</text>''',

        "brain": f'''
  <circle cx="28" cy="24" r="12" fill="{fill}" stroke="{stroke}" stroke-width="2"/>
  <circle cx="38" cy="24" r="12" fill="{fill}" stroke="{stroke}" stroke-width="2"/>
  <circle cx="28" cy="36" r="12" fill="{fill}" stroke="{stroke}" stroke-width="2"/>
  <circle cx="38" cy="36" r="12" fill="{fill}" stroke="{stroke}" stroke-width="2"/>
  <text x="32" y="34" text-anchor="middle" fill="white" font-size="{font_size}" font-family="Segoe UI,sans-serif" font-weight="600">{safe_label}</text>''',

        "chart": f'''
  <rect x="6" y="6" width="52" height="52" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="2"/>
  <rect x="14" y="32" width="8" height="18" rx="1" fill="white" opacity="0.7"/>
  <rect x="28" y="22" width="8" height="28" rx="1" fill="white" opacity="0.85"/>
  <rect x="42" y="14" width="8" height="36" rx="1" fill="white" opacity="1"/>
  <text x="32" y="60" text-anchor="middle" fill="{fill}" font-size="{min(font_size, 7)}" font-family="Segoe UI,sans-serif" font-weight="600">{safe_label}</text>''',

        "arrows": f'''
  <rect x="6" y="6" width="52" height="52" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="2"/>
  <path d="M18 32 H46 M38 24 L46 32 L38 40" stroke="white" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="32" y="56" text-anchor="middle" fill="{fill}" font-size="{min(font_size, 7)}" font-family="Segoe UI,sans-serif" font-weight="600">{safe_label}</text>''',

        "gear": f'''
  <circle cx="32" cy="30" r="22" fill="{fill}" stroke="{stroke}" stroke-width="2"/>
  <circle cx="32" cy="30" r="10" fill="white" opacity="0.3"/>
  <circle cx="32" cy="30" r="5" fill="white" opacity="0.6"/>
  <rect x="30" y="6" width="4" height="10" fill="{stroke}" rx="1"/>
  <rect x="30" y="44" width="4" height="10" fill="{stroke}" rx="1"/>
  <rect x="8" y="28" width="10" height="4" fill="{stroke}" rx="1"/>
  <rect x="46" y="28" width="10" height="4" fill="{stroke}" rx="1"/>
  <text x="32" y="60" text-anchor="middle" fill="{fill}" font-size="{min(font_size, 7)}" font-family="Segoe UI,sans-serif" font-weight="600">{safe_label}</text>''',

        "sliders": f'''
  <rect x="6" y="6" width="52" height="52" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="2"/>
  <line x1="18" y1="18" x2="18" y2="46" stroke="white" stroke-width="2"/>
  <circle cx="18" cy="26" r="4" fill="white"/>
  <line x1="32" y1="18" x2="32" y2="46" stroke="white" stroke-width="2"/>
  <circle cx="32" cy="38" r="4" fill="white"/>
  <line x1="46" y1="18" x2="46" y2="46" stroke="white" stroke-width="2"/>
  <circle cx="46" cy="30" r="4" fill="white"/>
  <text x="32" y="60" text-anchor="middle" fill="{fill}" font-size="{min(font_size, 7)}" font-family="Segoe UI,sans-serif" font-weight="600">{safe_label}</text>''',

        "circle": f'''
  <circle cx="32" cy="32" r="26" fill="{fill}" stroke="{stroke}" stroke-width="2"/>
  <text x="32" y="36" text-anchor="middle" fill="white" font-size="{font_size}" font-family="Segoe UI,sans-serif" font-weight="600">{safe_label}</text>''',

        "play": f'''
  <rect x="6" y="6" width="52" height="52" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="2"/>
  <polygon points="24,18 46,32 24,46" fill="white" opacity="0.9"/>
  <text x="32" y="60" text-anchor="middle" fill="{fill}" font-size="{min(font_size, 7)}" font-family="Segoe UI,sans-serif" font-weight="600">{safe_label}</text>''',

        "building": f'''
  <rect x="14" y="12" width="36" height="44" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="2"/>
  <rect x="20" y="18" width="8" height="6" rx="1" fill="white" opacity="0.5"/>
  <rect x="36" y="18" width="8" height="6" rx="1" fill="white" opacity="0.5"/>
  <rect x="20" y="28" width="8" height="6" rx="1" fill="white" opacity="0.5"/>
  <rect x="36" y="28" width="8" height="6" rx="1" fill="white" opacity="0.5"/>
  <rect x="26" y="42" width="12" height="14" rx="1" fill="white" opacity="0.7"/>
  <text x="32" y="10" text-anchor="middle" fill="{fill}" font-size="{min(font_size, 7)}" font-family="Segoe UI,sans-serif" font-weight="600">{safe_label}</text>''',
    }

    body = shapes.get(shape, shapes["circle"])
    return f"{header}{body}\n{footer}\n"


def _slugify(text: str) -> str:
    """Convert text to a filename-safe slug."""
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s


def _load_services(filepath: str) -> list[dict]:
    """Load a Python service catalog by parsing the list literal."""
    # Quick approach: exec the file and grab the variable
    ns: dict = {}
    with open(filepath) as f:
        exec(f.read(), ns)  # noqa: S102
    # Find the first list value
    for v in ns.values():
        if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
            return v
    return []


def generate_pack(
    provider: str,
    services: list[dict],
    output_dir: str,
) -> dict:
    """Generate SVG icons and metadata.json for a provider."""
    os.makedirs(output_dir, exist_ok=True)
    palette = PALETTES.get(provider, AZURE_PALETTE)
    default_colors = ("#666666", "#444444", "#999999")

    manifest_icons = []
    seen_ids = set()

    for svc in services:
        svc_id = svc.get("id", "")
        name = svc.get("name", svc.get("fullName", svc.get("full_name", svc_id)))
        category = svc.get("category", "General")
        # Normalize category to palette keys
        cat_key = category
        for key in palette:
            if key.lower() == category.lower():
                cat_key = key
                break

        if svc_id in seen_ids:
            continue
        seen_ids.add(svc_id)

        fill, stroke, accent = palette.get(cat_key, default_colors)
        shape = CATEGORY_SHAPES.get(cat_key, "circle")
        label = _abbreviate(name)
        slug = _slugify(name)
        filename = f"{slug}.svg"

        svg_content = _shape_svg(shape, fill, stroke, accent, label)

        svg_path = os.path.join(output_dir, filename)
        with open(svg_path, "w") as f:
            f.write(svg_content)

        # Build tags from name words + category
        tags = [w.lower() for w in re.split(r"[\s/()-]+", name) if len(w) > 1]
        tags.append(category.lower())
        tags = list(dict.fromkeys(tags))  # dedupe while preserving order

        manifest_icons.append({
            "file": filename,
            "name": name,
            "category": category.lower(),
            "tags": tags,
            "service_id": svc_id,
        })

    # Sort for determinism
    manifest_icons.sort(key=lambda x: x["service_id"])

    manifest = {
        "name": f"{provider.upper()} Services",
        "provider": provider,
        "version": "1.0.0",
        "description": f"Complete {provider.upper()} service icon pack ({len(manifest_icons)} icons)",
        "icons": manifest_icons,
    }

    manifest_path = os.path.join(output_dir, "metadata.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return manifest


def main():
    """Generate all three provider icon packs."""
    base = os.path.dirname(os.path.abspath(__file__))

    # Locate service catalogs
    providers = {
        "azure": os.path.join(base, "services", "azure_services.py"),
        "aws":   os.path.join(base, "services", "aws_services.py"),
        "gcp":   os.path.join(base, "services", "gcp_services.py"),
    }

    for provider, catalog_path in providers.items():
        if not os.path.exists(catalog_path):
            print(f"  SKIP {provider}: {catalog_path} not found")
            continue

        services = _load_services(catalog_path)
        output_dir = os.path.join(base, "samples", provider)

        manifest = generate_pack(provider, services, output_dir)
        print(f"  {provider.upper()}: {len(manifest['icons'])} icons → {output_dir}")

    print("\nDone! Icon packs generated in backend/samples/")


if __name__ == "__main__":
    main()
