"""
Archmorph Vision Analyzer — GPT-4o powered diagram analysis.

Uses Azure OpenAI GPT-4o with vision capabilities to detect cloud services
from architecture diagram images, then maps them to Azure equivalents using
the cross-cloud service catalog.
"""

import base64
import hashlib
import io
import json
import logging
import os
import threading
from difflib import SequenceMatcher
from typing import Any, Dict, Optional, Tuple

from PIL import Image

from services import AWS_SERVICES, GCP_SERVICES, CROSS_CLOUD_MAPPINGS
from openai_client import get_openai_client, AZURE_OPENAI_DEPLOYMENT, openai_retry
from prompt_guard import PROMPT_ARMOR

from cachetools import TTLCache

# Maximum image dimension for GPT-4o vision (keeps quality while reducing tokens)
MAX_IMAGE_DIMENSION = 2048
JPEG_QUALITY = 85

# Adaptive detail thresholds (Issue #178 — token cost optimization)
# Images smaller than this use "low" detail (fixed 85 tokens).
# Larger images use "high" detail (variable, up to ~5x more tokens).
_LOW_DETAIL_MAX_PIXELS = 512 * 512  # 262 144 px
_LOW_DETAIL_MAX_BYTES = 150_000     # ~150 KB compressed


def _pick_detail_level(image_bytes: bytes, width: int, height: int) -> str:
    """Choose GPT-4o vision detail level adaptively (Issue #178).

    * ``low``  — 512x512 fixed-token budget (85 tokens). Good for simple
      diagrams with large, clearly-labelled icons.
    * ``high`` — tile-based tokenisation, up to ~5x more tokens.  Needed for
      complex multi-zone diagrams with small text/icons.

    The heuristic uses *compressed* byte size and pixel count to decide.
    """
    total_pixels = width * height
    if total_pixels <= _LOW_DETAIL_MAX_PIXELS and len(image_bytes) <= _LOW_DETAIL_MAX_BYTES:
        return "low"
    return "high"


def compress_image(image_bytes: bytes, content_type: str = "image/png") -> Tuple[bytes, str, int, int]:
    """
    Resize & compress an image before sending to GPT-4o.

    - Caps the longest edge at MAX_IMAGE_DIMENSION px
    - Converts to JPEG (lossy, much smaller than PNG)
    - Returns (compressed_bytes, new_content_type, width, height)
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

        final_w, final_h = img.size
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        compressed = buf.getvalue()
        logger.info(
            "Compressed image: %d → %d bytes (%.0f%% reduction)",
            len(image_bytes), len(compressed),
            (1 - len(compressed) / max(len(image_bytes), 1)) * 100,
        )
        return compressed, "image/jpeg", final_w, final_h
    except Exception as exc:
        logger.warning("Image compression failed (%s) — using original", exc)
        return image_bytes, content_type, 0, 0

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Vision analysis cache — avoids redundant GPT-4o calls for
# the same image (Issue #295).  Keyed by SHA-256 of compressed bytes.
# ─────────────────────────────────────────────────────────────
_VISION_CACHE_TTL = int(os.getenv("VISION_CACHE_TTL", "3600"))
_VISION_CACHE_MAX = int(os.getenv("VISION_CACHE_MAX", "64"))
_vision_cache: TTLCache = TTLCache(maxsize=_VISION_CACHE_MAX, ttl=_VISION_CACHE_TTL)
_vision_cache_lock = threading.Lock()

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

# Mapping index by AWS / GCP / Azure short name
_MAPPING_BY_AWS: Dict[str, Dict] = {}
for m in CROSS_CLOUD_MAPPINGS:
    _MAPPING_BY_AWS[m["aws"].lower()] = m

_MAPPING_BY_GCP: Dict[str, Dict] = {}
for m in CROSS_CLOUD_MAPPINGS:
    if m.get("gcp"):
        _MAPPING_BY_GCP[m["gcp"].lower()] = m

_MAPPING_BY_AZURE: Dict[str, Dict] = {}
for m in CROSS_CLOUD_MAPPINGS:
    if m.get("azure"):
        _MAPPING_BY_AZURE[m["azure"].lower()] = m

_MAPPING_INDEX = {
    "aws": _MAPPING_BY_AWS,
    "gcp": _MAPPING_BY_GCP,
    "azure": _MAPPING_BY_AZURE,
}

# Supported target providers
SUPPORTED_TARGETS = ("azure", "aws", "gcp")


def _get_target_field(target_provider: str) -> str:
    """Return the CROSS_CLOUD_MAPPINGS field name for the given target cloud."""
    return target_provider.lower()  # "aws", "azure", or "gcp"

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
    short_name: str, source_provider: str, target_provider: str = "azure"
) -> Optional[Dict]:
    """Find the cross-cloud mapping for a service short name.

    Args:
        short_name: The source service short name (e.g. "EC2", "Cloud Run").
        source_provider: The source cloud ("aws", "gcp", "azure").
        target_provider: The target cloud to map to ("azure", "aws", "gcp").
    """
    key = short_name.lower().strip()

    # 1. Check synonyms first to canonicalize the name
    if key in _SYNONYMS:
        key = _SYNONYMS[key]

    target_field = _get_target_field(target_provider)

    # Get the mapping index for the source provider
    source_index = _MAPPING_INDEX.get(source_provider, _MAPPING_BY_AWS)

    # Direct or partial match against source provider mappings
    if key in source_index:
        m = source_index[key]
        if m.get(target_field):
            return m
    # Try partial match
    for mapping_key, mapping in source_index.items():
        if (mapping_key in key or key in mapping_key) and mapping.get(target_field):
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

    # 3. Fuzzy semantic matching fallback — O(n) but with early cutoff (Issue #143)
    #    Use get_close_matches for built-in heap optimization instead of
    #    manually scanning every key with SequenceMatcher.
    from difflib import get_close_matches as _gcm

    close = _gcm(key, source_index.keys(), n=1, cutoff=0.65)
    if close:
        best_key = close[0]
        best_ratio = SequenceMatcher(None, key, best_key).ratio()
        result = dict(source_index[best_key])
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
    compressed_bytes, compressed_type, img_w, img_h = compress_image(image_bytes, content_type)

    # Ensure bytes for hashing (guard against str from Redis/JSON round-trip)
    if isinstance(compressed_bytes, str):
        compressed_bytes = compressed_bytes.encode("utf-8")

    # Check vision cache before calling GPT-4o (Issue #295)
    cache_key = hashlib.sha256(compressed_bytes).hexdigest()
    with _vision_cache_lock:
        cached = _vision_cache.get(cache_key)
    if cached is not None:
        logger.info("Vision cache HIT (key=%s…)", cache_key[:12])
        return cached

    # Adaptive detail level — saves ~5x tokens for small/simple diagrams (Issue #178)
    detail = _pick_detail_level(compressed_bytes, img_w, img_h)

    # Encode image to base64
    b64_image = base64.b64encode(compressed_bytes).decode("utf-8")
    media_type = compressed_type

    # Call GPT-4o with vision
    client = get_openai_client()

    logger.info(
        "Sending image to GPT-4o for analysis (%d bytes, %s, detail=%s, %dx%d)",
        len(compressed_bytes),
        media_type,
        detail,
        img_w,
        img_h,
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
                            "detail": detail,
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

    # Detect GPT output truncation (Issue #278)
    if response.choices[0].finish_reason == "length":
        logger.warning(
            "Vision analysis output TRUNCATED (finish_reason=length). "
            "JSON may be invalid or incomplete — some services may be missing."
        )

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

    result = _build_analysis_result(vision_result)

    # Store in vision cache (Issue #295)
    with _vision_cache_lock:
        _vision_cache[cache_key] = result
    logger.info("Vision cache STORE (key=%s…)", cache_key[:12])

    return result


def _build_analysis_result(vision_result: Dict[str, Any], target_provider: str = "azure") -> Dict[str, Any]:
    """
    Convert the GPT-4o vision output into the full analysis result
    with ServiceMapping objects and target cloud equivalents.

    Args:
        vision_result: Raw GPT-4o parsed output.
        target_provider: Target cloud to map to ("azure", "aws", "gcp").
    """
    source_provider = vision_result.get("source_provider", "aws")
    diagram_type = vision_result.get("diagram_type", "Cloud Architecture")
    patterns = vision_result.get("architecture_patterns", [])
    compliance = vision_result.get("compliance_hints", [])
    zones_data = vision_result.get("zones", [])

    target_field = _get_target_field(target_provider)

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

            # Find target cloud mapping
            mapping = _find_azure_mapping(short_name, source_provider, target_provider)

            if mapping:
                target_service = mapping.get(target_field, mapping.get("azure", ""))
                # Blend mapping confidence with GPT-4o detection confidence
                mapping_conf = mapping["confidence"]
                confidence = round(mapping_conf * 0.7 + detection_conf * 0.3, 2)
                confidence = min(1.0, max(0.0, confidence))
                notes = mapping.get("notes", "")
                category = mapping.get("category", "General")

                # Build human-readable confidence explanation
                confidence_reasons = []
                confidence_reasons.append(
                    f"Curated mapping confidence: {int(mapping_conf * 100)}% — "
                    f"{notes or 'verified cross-cloud service equivalence'}"
                )
                confidence_reasons.append(
                    f"Diagram detection confidence: {int(detection_conf * 100)}% — "
                    f"how clearly this service was identified in the uploaded diagram"
                )
                confidence_reasons.append(
                    f"Blended score: 70% mapping ({int(mapping_conf * 100)}%) "
                    f"+ 30% detection ({int(detection_conf * 100)}%) = {int(confidence * 100)}%"
                )
            else:
                # No direct mapping found — flag it
                target_service = f"[Manual mapping needed] {full_name}"
                confidence = round(0.30 * 0.7 + detection_conf * 0.3, 2)
                notes = f"No direct cross-cloud mapping found for {full_name}"
                category = "General"
                warnings.append(
                    f"{full_name} — no automatic {target_provider.upper()} mapping found; manual review required"
                )
                confidence_reasons = [
                    f"No curated mapping found for {full_name} — base mapping score set to 30%",
                    f"Diagram detection confidence: {int(detection_conf * 100)}%",
                    "Manual review recommended to confirm the best target service",
                ]

            # Build mapping entry (keep azure_service key for backward compat)
            mapping_entry = {
                "source_service": full_name,
                "source_provider": source_provider,
                "azure_service": target_service,
                "target_service": target_service,
                "target_provider": target_provider,
                "confidence": confidence,
                "confidence_explanation": confidence_reasons,
                "notes": f"Zone {zone_number} – {zone_name}: {role}. {notes}".strip(),
            }
            mappings.append(mapping_entry)

            zone_services.append({
                "source": full_name,
                "source_provider": source_provider,
                "azure": target_service,
                "target": target_service,
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
        "target_provider": target_provider,
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
            "methodology": (
                "Each confidence score is calculated by blending two factors: "
                "(1) a curated mapping confidence from our verified cross-cloud service database (weighted 70%), "
                "reflecting how closely the source and target services match in features and capabilities; and "
                "(2) an AI detection confidence (weighted 30%), representing how clearly the service was identified "
                "in your uploaded diagram. Scores above 90% indicate a direct, well-established equivalent. "
                "Scores between 80-90% indicate a strong match with minor feature differences. "
                "Scores below 80% indicate significant differences that may require architectural adjustments."
            ),
        },
    }
