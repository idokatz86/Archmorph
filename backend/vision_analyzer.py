"""
Archmorph Vision Analyzer — GPT-4o powered diagram analysis.

Uses Azure OpenAI GPT-4o with vision capabilities to detect cloud services
from architecture diagram images, then maps them to Azure equivalents using
the cross-cloud service catalog.
"""

import base64
import io
import json
import logging
from difflib import SequenceMatcher
from typing import Any, Dict, Optional

from PIL import Image

from services import AWS_SERVICES, GCP_SERVICES, CROSS_CLOUD_MAPPINGS
from openai_client import get_openai_client, AZURE_OPENAI_DEPLOYMENT, openai_retry
from prompt_guard import PROMPT_ARMOR

# Maximum image dimension for GPT-4o vision (keeps quality while reducing tokens)
MAX_IMAGE_DIMENSION = 2048
JPEG_QUALITY = 85


def compress_image(image_bytes: bytes, content_type: str = "image/png") -> tuple[bytes, str]:
    """
    Resize & compress an image before sending to GPT-4o.

    - Caps the longest edge at MAX_IMAGE_DIMENSION px
    - Converts to JPEG (lossy, much smaller than PNG)
    - Returns (compressed_bytes, new_content_type)
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))

        # Convert palette / RGBA to RGB for JPEG
        if img.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Resize if too large
        w, h = img.size
        if max(w, h) > MAX_IMAGE_DIMENSION:
            ratio = MAX_IMAGE_DIMENSION / max(w, h)
            new_size = (int(w * ratio), int(h * ratio))
            img = img.resize(new_size, Image.LANCZOS)
            logger.info("Resized image from %dx%d to %dx%d", w, h, *new_size)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        compressed = buf.getvalue()
        logger.info(
            "Compressed image: %d → %d bytes (%.0f%% reduction)",
            len(image_bytes), len(compressed),
            (1 - len(compressed) / max(len(image_bytes), 1)) * 100,
        )
        return compressed, "image/jpeg"
    except Exception as exc:
        logger.warning("Image compression failed (%s) — using original", exc)
        return image_bytes, content_type

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Build service name lookup indexes
# ─────────────────────────────────────────────────────────────
_AWS_NAME_INDEX: Dict[str, Dict] = {}
for svc in AWS_SERVICES:
    _AWS_NAME_INDEX[svc["name"].lower()] = svc
    _AWS_NAME_INDEX[svc["fullName"].lower()] = svc
    # Also index without "Amazon " or "AWS " prefix
    for prefix in ("Amazon ", "AWS "):
        if svc["fullName"].startswith(prefix):
            _AWS_NAME_INDEX[svc["fullName"][len(prefix):].lower()] = svc

_GCP_NAME_INDEX: Dict[str, Dict] = {}
for svc in GCP_SERVICES:
    _GCP_NAME_INDEX[svc["name"].lower()] = svc
    _GCP_NAME_INDEX[svc["fullName"].lower()] = svc
    for prefix in ("Google ", "Google Cloud ", "Cloud "):
        if svc["fullName"].startswith(prefix):
            _GCP_NAME_INDEX[svc["fullName"][len(prefix):].lower()] = svc

# Mapping index by AWS / GCP short name
_MAPPING_BY_AWS: Dict[str, Dict] = {}
for m in CROSS_CLOUD_MAPPINGS:
    _MAPPING_BY_AWS[m["aws"].lower()] = m

_MAPPING_BY_GCP: Dict[str, Dict] = {}
for m in CROSS_CLOUD_MAPPINGS:
    if m.get("gcp"):
        _MAPPING_BY_GCP[m["gcp"].lower()] = m

# ─────────────────────────────────────────────────────────────
# Infrastructure element mappings (not full "services" but common
# architecture components that GPT-4o detects in diagrams)
# ─────────────────────────────────────────────────────────────
_INFRA_MAPPINGS: Dict[str, Dict] = {
    # Networking elements
    "internet gateway": {"azure": "Internet (via VNet)", "confidence": 0.95, "category": "Networking", "notes": "Azure VNet has implicit internet connectivity via public IPs"},
    "nat gateway": {"azure": "Azure NAT Gateway", "confidence": 0.95, "category": "Networking", "notes": "Direct equivalent — outbound internet for private subnets"},
    "public subnet": {"azure": "Azure Subnet (public)", "confidence": 0.95, "category": "Networking", "notes": "Azure uses NSGs for public/private distinction, not subnet types"},
    "private subnet": {"azure": "Azure Subnet (private)", "confidence": 0.95, "category": "Networking", "notes": "Azure uses NSGs + Private Endpoints for network isolation"},
    "availability zone": {"azure": "Azure Availability Zone", "confidence": 0.95, "category": "Networking", "notes": "Direct equivalent — AZ isolation within a region"},
    "alb": {"azure": "Azure Application Gateway", "confidence": 0.90, "category": "Networking", "notes": "Application Load Balancer → L7 load balancing"},
    "nlb": {"azure": "Azure Load Balancer", "confidence": 0.90, "category": "Networking", "notes": "Network Load Balancer → L4 load balancing"},
    "security group": {"azure": "Network Security Group (NSG)", "confidence": 0.95, "category": "Networking", "notes": "Direct equivalent — stateful packet filtering"},
    "route table": {"azure": "Azure Route Table (UDR)", "confidence": 0.95, "category": "Networking", "notes": "User-defined routes for custom traffic routing"},
    # Compute elements
    "bastion host": {"azure": "Azure Bastion", "confidence": 0.95, "category": "Compute", "notes": "Managed bastion service — no VM needed on Azure"},
    "auto scaling group": {"azure": "VM Scale Sets", "confidence": 0.95, "category": "Compute", "notes": "Auto Scaling Group → VMSS with autoscale rules"},
    "ec2": {"azure": "Azure Virtual Machines", "confidence": 0.95, "category": "Compute", "notes": "Direct IaaS VM equivalent"},
    "web application": {"azure": "Azure App Service", "confidence": 0.90, "category": "Compute", "notes": "PaaS web hosting — App Service or Static Web Apps"},
    "amplify": {"azure": "Azure Static Web Apps", "confidence": 0.85, "category": "Compute", "notes": "Frontend hosting with CI/CD integration"},
    "contact flows": {"azure": "Azure Bot Service (Workflows)", "confidence": 0.75, "category": "Business", "notes": "Voice/chat IVR flow design"},
    # Storage elements
    "nfs server": {"azure": "Azure Files (NFS)", "confidence": 0.90, "category": "Storage", "notes": "Azure Files with NFS v4.1 protocol or Azure NetApp Files"},
    "nfs": {"azure": "Azure Files (NFS)", "confidence": 0.90, "category": "Storage", "notes": "Azure Files NFS or Azure NetApp Files for high performance"},
}

# Synonym map: alternate names → canonical mapping key
_SYNONYMS: Dict[str, str] = {
    "elasticsearch": "opensearch",
    "amazon elasticsearch service": "opensearch",
    "amazon elasticsearch": "opensearch",
    "elasticsearch service": "opensearch",
    "elastic load balancing": "elb",
    "application load balancer": "elb",
    "network load balancer": "elb",
    "classic load balancer": "elb",
    "auto scaling": "ec2 auto scaling",
    "rds postgresql": "rds",
    "rds mysql": "rds",
    "rds aurora": "aurora",
    "amazon connect": "connect",
    "amazon lex": "lex",
    "amazon pinpoint": "pinpoint",
    "amazon dynamodb": "dynamodb",
    "amazon cognito": "cognito",
    "aws lambda": "lambda",
    "amazon s3": "s3",
    "amazon ec2": "ec2",
    "amazon vpc": "vpc",
    "amazon ecs": "ecs",
    "amazon eks": "eks",
    "amazon efs": "efs",
    "amazon rds": "rds",
    "amazon cloudfront": "cloudfront",
    "amazon cloudwatch": "cloudwatch",
    "amazon guardduty": "guardduty",
    "amazon sqs": "sqs",
    "amazon sns": "sns",
    "amazon kinesis": "kinesis",
    "aws iam": "iam",
    "aws kms": "kms",
    "aws waf": "waf",
    "aws cloudtrail": "cloudtrail",
    "aws security hub": "security hub",
    "aws backup": "backup",
    "amazon elasticache": "elasticache",
    "amazon api gateway": "api gateway",
    "eks cluster": "eks",
    "aws amplify": "amplify",
    # ── GCP synonyms ─────────────────────────────────────────
    "load balancer": "cloud load balancing",
    "gcp load balancer": "cloud load balancing",
    "google load balancer": "cloud load balancing",
    "cloud load balancer": "cloud load balancing",
    "google cloud load balancing": "cloud load balancing",
    "google managed ssl": "certificate manager",
    "managed ssl": "certificate manager",
    "managed ssl certificate": "certificate manager",
    "google managed ssl certificate": "certificate manager",
    "ssl certificate": "certificate manager",
    "google certificate manager": "certificate manager",
    "gcp certificate manager": "certificate manager",
    "cloud ssl": "certificate manager",
    "google cloud storage": "cloud storage",
    "gcp storage": "cloud storage",
    "google cloud functions": "cloud functions",
    "gcp functions": "cloud functions",
    "google compute engine": "compute engine",
    "gcp compute": "compute engine",
    "google kubernetes engine": "gke",
    "gcp kubernetes": "gke",
    "google cloud sql": "cloud sql",
    "gcp cloud sql": "cloud sql",
    "google cloud pub/sub": "cloud pub/sub",
    "gcp pub/sub": "cloud pub/sub",
    "google cloud run": "cloud run",
    "gcp cloud run": "cloud run",
    "google bigquery": "bigquery",
    "gcp bigquery": "bigquery",
    "google cloud cdn": "cloud cdn",
    "gcp cdn": "cloud cdn",
    "google cloud armor": "cloud armor",
    "gcp cloud armor": "cloud armor",
    "google cloud dns": "cloud dns",
    "gcp cloud dns": "cloud dns",
    "google cloud spanner": "cloud spanner",
    "gcp spanner": "cloud spanner",
    "google dataflow": "dataflow",
    "gcp dataflow": "dataflow",
    "google dataproc": "dataproc",
    "gcp dataproc": "dataproc",
    "google cloud iam": "cloud iam",
    "gcp iam": "cloud iam",
    "google cloud kms": "cloud kms",
    "gcp kms": "cloud kms",
    "google memorystore": "memorystore",
    "gcp memorystore": "memorystore",
    "google filestore": "filestore",
    "gcp filestore": "filestore",
    "google cloud logging": "cloud logging",
    "gcp logging": "cloud logging",
    "google cloud monitoring": "cloud monitoring",
    "gcp monitoring": "cloud monitoring",
    "google vertex ai": "vertex ai",
    "gcp vertex ai": "vertex ai",
    "google cloud endpoints": "cloud endpoints",
    "gcp endpoints": "cloud endpoints",
    "google app engine": "app engine",
    "gcp app engine": "app engine",
    "google firebase": "firebase",
    "gcp firebase": "firebase",
    "google anthos": "anthos",
    "gcp anthos": "anthos",
    "google cloud interconnect": "cloud interconnect",
    "gcp interconnect": "cloud interconnect",
    "google cloud vpn": "cloud vpn",
    "gcp vpn": "cloud vpn",
}

# ─────────────────────────────────────────────────────────────
# System prompt for diagram analysis
# ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a cloud architecture diagram analyzer. Your job is to examine an architecture diagram image and extract EVERY cloud service shown.

RULES:
1. Identify all cloud services visible in the diagram (AWS, GCP, or on-premises components).
2. Detect the source cloud provider (aws or gcp). Look for provider-specific clues:
   - GCP indicators: Google Cloud logo, "GCP" text, services like Pub/Sub, BigQuery, Cloud Storage, Cloud Run, GKE, Compute Engine, Cloud Functions, Dataflow, Cloud SQL, Firestore, Spanner, Cloud CDN, Cloud Armor, Cloud DNS, Vertex AI, Anthos, Cloud Interconnect, App Engine, Firebase, Memorystore, Filestore, Cloud IoT Core, Dataproc, Cloud Logging, Cloud Monitoring, etc.
   - AWS indicators: AWS logo, services like S3, EC2, Lambda, RDS, DynamoDB, SQS, SNS, ECS, EKS, CloudFront, Route 53, Kinesis, API Gateway, CloudWatch, etc.
   IMPORTANT: If you see ANY GCP service names or the Google Cloud logo, set source_provider to "gcp". Do NOT default to "aws" when the diagram is clearly GCP.
3. Group services into logical architecture zones (e.g., "Networking", "Compute", "Database", "Security", "Storage", "Frontend", "Backend", etc.).
4. For each service, provide:
   - The exact service name as shown in the diagram (e.g., "Amazon RDS", "Lambda", "S3")
   - A short_name using the CANONICAL AWS/GCP service name for catalog lookup (use official names like "RDS", "Lambda", "S3", "EKS", "Cloud Load Balancing", "Certificate Manager", "Cloud Storage", "Compute Engine", etc.)
   - The role or purpose it plays in this architecture
   - detection_confidence: a float 0.0–1.0 rating how certain you are that this service was correctly identified (1.0 = clearly labeled icon, 0.5 = inferred from context, 0.3 = uncertain guess)
   - The zone/layer it belongs to
5. Also identify:
   - Architecture patterns (e.g., "multi-AZ", "serverless", "microservices", "data pipeline")
   - Networking constructs (VPCs, subnets, availability zones, load balancers)
   - Data flow connections between services (from → to)
   - Any compliance/regulatory hints (HIPAA, PCI, etc.)

CANONICAL NAME EXAMPLES:
- AWS: "EC2", "S3", "RDS", "Lambda", "ECS", "EKS", "CloudFront", "Route 53", "VPC", "ELB", "DynamoDB", "SQS", "SNS", "Kinesis", "API Gateway", "CloudWatch", "IAM", "KMS"
- GCP: "Compute Engine", "Cloud Storage", "Cloud SQL", "Cloud Functions", "GKE", "Cloud Load Balancing", "Cloud CDN", "Cloud DNS", "BigQuery", "Pub/Sub", "Cloud Run", "Dataflow", "Certificate Manager"

IMPORTANT: Be thorough — extract EVERY service icon, label, and component visible. Don't skip small components. Include infrastructure elements like VPC, subnets, internet gateways, NAT gateways, etc.

Respond ONLY with valid JSON in this exact format:
{
  "diagram_type": "<short description of the architecture>",
  "source_provider": "aws" | "gcp",
  "architecture_patterns": ["pattern1", "pattern2"],
  "compliance_hints": ["hint1"],
  "service_connections": [
    {"from": "<service short_name>", "to": "<service short_name>", "protocol": "<HTTPS/gRPC/TCP/event/etc>"}
  ],
  "zones": [
    {
      "name": "<zone name>",
      "number": <zone number starting from 1>,
      "services": [
        {
          "name": "<full service name as shown>",
          "short_name": "<canonical service name for catalog lookup>",
          "role": "<what it does in this architecture>",
          "detection_confidence": 0.95
        }
      ]
    }
  ]
}
""" + PROMPT_ARMOR


def _find_azure_mapping(
    short_name: str, source_provider: str
) -> Optional[Dict]:
    """Find the cross-cloud mapping for a service short name."""
    key = short_name.lower().strip()

    # 1. Check synonyms first to canonicalize the name
    if key in _SYNONYMS:
        key = _SYNONYMS[key]

    if source_provider == "aws":
        # Direct match
        if key in _MAPPING_BY_AWS:
            return _MAPPING_BY_AWS[key]
        # Try partial match — e.g. "RDS PostgreSQL" → "RDS"
        for mapping_key, mapping in _MAPPING_BY_AWS.items():
            if mapping_key in key or key in mapping_key:
                return mapping
    elif source_provider == "gcp":
        if key in _MAPPING_BY_GCP:
            return _MAPPING_BY_GCP[key]
        for mapping_key, mapping in _MAPPING_BY_GCP.items():
            if mapping_key in key or key in mapping_key:
                return mapping

    # 2. Check infrastructure element mappings
    for infra_key, infra_map in _INFRA_MAPPINGS.items():
        if infra_key in key or key in infra_key:
            return {
                "aws": short_name,
                "azure": infra_map["azure"],
                "gcp": "",
                "category": infra_map["category"],
                "confidence": infra_map["confidence"],
                "notes": infra_map["notes"],
            }

    # 3. Fuzzy semantic matching fallback — find best match by string similarity
    best_match = None
    best_ratio = 0.0
    all_mappings = _MAPPING_BY_AWS if source_provider == "aws" else _MAPPING_BY_GCP
    for mapping_key, mapping in all_mappings.items():
        ratio = SequenceMatcher(None, key, mapping_key).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = mapping
    # Accept fuzzy match if similarity ≥ 65%
    if best_match and best_ratio >= 0.65:
        result = dict(best_match)
        # Penalize confidence based on fuzzy match quality
        result["confidence"] = round(result["confidence"] * best_ratio, 2)
        result["notes"] = f"Fuzzy match ({best_ratio:.0%} similarity). " + result.get("notes", "")
        return result

    return None


def analyze_image(image_bytes: bytes, content_type: str = "image/png") -> Dict[str, Any]:
    """
    Analyze a cloud architecture diagram image using GPT-4o vision.

    Args:
        image_bytes: Raw image bytes (PNG, JPEG, etc.)
        content_type: MIME type of the image

    Returns:
        Full analysis result dict with mappings, zones, warnings, confidence_summary.
    """
    # Compress image to reduce tokens and latency
    compressed_bytes, compressed_type = compress_image(image_bytes, content_type)

    # Encode image to base64
    b64_image = base64.b64encode(compressed_bytes).decode("utf-8")
    media_type = compressed_type

    # Call GPT-4o with vision
    client = get_openai_client()

    logger.info(
        "Sending image to GPT-4o for analysis (%d bytes, %s)",
        len(compressed_bytes),
        media_type,
    )

    response = openai_retry(client.chat.completions.create)(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Analyze this cloud architecture diagram. Extract every service, component, and infrastructure element visible. Be thorough and precise.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{b64_image}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
        max_tokens=16384,
        temperature=0.1,
        response_format={"type": "json_object"},  # Enforce JSON output
    )

    raw_text = response.choices[0].message.content.strip()
    logger.info("GPT-4o response received (%d chars)", len(raw_text))

    # Parse JSON from response (handle ```json blocks)
    json_text = raw_text
    if "```json" in json_text:
        json_text = json_text.split("```json", 1)[1]
        json_text = json_text.split("```", 1)[0]
    elif "```" in json_text:
        json_text = json_text.split("```", 1)[1]
        json_text = json_text.split("```", 1)[0]

    try:
        vision_result = json.loads(json_text.strip())
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse GPT-4o JSON: %s\nRaw: %s", exc, raw_text[:500])
        raise ValueError(f"GPT-4o returned invalid JSON: {exc}") from exc

    return _build_analysis_result(vision_result)


def _build_analysis_result(vision_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert the GPT-4o vision output into the full analysis result
    with ServiceMapping objects and Azure equivalents.
    """
    source_provider = vision_result.get("source_provider", "aws")
    diagram_type = vision_result.get("diagram_type", "Cloud Architecture")
    patterns = vision_result.get("architecture_patterns", [])
    compliance = vision_result.get("compliance_hints", [])
    zones_data = vision_result.get("zones", [])

    mappings = []
    warnings = []
    zones_with_services = []
    seen_services = set()  # Track duplicates

    for zone in zones_data:
        zone_name = zone.get("name", "Unknown")
        zone_number = zone.get("number", 0)
        zone_services = []

        for svc in zone.get("services", []):
            full_name = svc.get("name", "")
            short_name = svc.get("short_name", full_name)
            role = svc.get("role", "")

            # GPT-4o detection confidence (how sure it is about identifying this service)
            detection_conf = svc.get("detection_confidence", 0.85)

            # Find Azure mapping
            mapping = _find_azure_mapping(short_name, source_provider)

            if mapping:
                azure_service = mapping["azure"]
                # Blend mapping confidence with GPT-4o detection confidence
                mapping_conf = mapping["confidence"]
                confidence = round(mapping_conf * 0.7 + detection_conf * 0.3, 2)
                confidence = min(1.0, max(0.0, confidence))
                notes = mapping.get("notes", "")
                mapping.get("category", "General")
            else:
                # No direct mapping found — flag it
                azure_service = f"[Manual mapping needed] {full_name}"
                confidence = round(0.30 * 0.7 + detection_conf * 0.3, 2)
                notes = f"No direct cross-cloud mapping found for {full_name}"
                warnings.append(
                    f"{full_name} — no automatic Azure mapping found; manual review required"
                )

            # Build mapping entry
            mapping_entry = {
                "source_service": full_name,
                "source_provider": source_provider,
                "azure_service": azure_service,
                "confidence": confidence,
                "notes": f"Zone {zone_number} – {zone_name}: {role}. {notes}".strip(),
            }
            mappings.append(mapping_entry)

            zone_services.append({
                "source": full_name,
                "source_provider": source_provider,
                "azure": azure_service,
                "confidence": confidence,
            })

            # Track duplicate services
            svc_key = short_name.lower()
            if svc_key in seen_services:
                pass  # Will aggregate below
            seen_services.add(svc_key)

        zones_with_services.append({
            "id": zone_number,
            "name": zone_name,
            "number": zone_number,
            "services": zone_services,
        })

    # Detect duplicates and add warnings
    name_counts: Dict[str, int] = {}
    for m in mappings:
        key = m["source_service"].split("(")[0].strip()
        name_counts[key] = name_counts.get(key, 0) + 1
    for name, count in name_counts.items():
        if count > 1:
            warnings.append(
                f"{name} appears {count}× across different zones — review for consolidation"
            )

    # Add pattern-based warnings
    if compliance:
        warnings.append(
            f"Compliance requirements detected: {', '.join(compliance)}. "
            "Ensure Azure architecture meets all regulatory standards."
        )

    # Confidence summary
    high = len([m for m in mappings if m["confidence"] >= 0.90])
    medium = len([m for m in mappings if 0.80 <= m["confidence"] < 0.90])
    low = len([m for m in mappings if m["confidence"] < 0.80])
    avg = round(sum(m["confidence"] for m in mappings) / max(len(mappings), 1), 2)

    # Extract service connections (dependency graph)
    connections = vision_result.get("service_connections", [])

    return {
        "diagram_type": diagram_type,
        "source_provider": source_provider,
        "target_provider": "azure",
        "architecture_patterns": patterns,
        "services_detected": len(mappings),
        "zones": zones_with_services,
        "mappings": mappings,
        "warnings": warnings,
        "service_connections": connections,
        "confidence_summary": {
            "high": high,
            "medium": medium,
            "low": low,
            "average": avg,
        },
    }
