"""
Archmorph Vision Analyzer — Direct GPT-4o powered diagram analysis.
Upgraded to Native Multimodal (Issue #417).
"""
import base64
import hashlib
import io
import json
import logging
from typing import Any, Dict, Tuple

from PIL import Image
from cachetools import TTLCache
import threading

from openai_client import get_openai_client, AZURE_OPENAI_DEPLOYMENT, openai_retry
from prompt_guard import PROMPT_ARMOR

logger = logging.getLogger(__name__)

# Maximum image dimension for GPT-4o vision (keeps quality while reducing tokens)
MAX_IMAGE_DIMENSION = 2048
JPEG_QUALITY = 85

# Thread-safe in-memory cache for vision results
_vision_cache = TTLCache(maxsize=100, ttl=3600)
_vision_cache_lock = threading.Lock()

def compress_image(image_bytes: bytes, content_type: str = "image/png") -> Tuple[bytes, str, int, int]:
    """
    Ensures image is max 2048px (maintaining aspect ratio), converting it to JPEG.
    Returns (compressed_bytes, new_content_type, width, height)
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            # Handle EXIF orientation
            if hasattr(img, "_getexif") and img._getexif():
                from PIL import ExifTags
                exif = img._getexif()
                orientation_key = next(
                    (k for k, v in ExifTags.TAGS.items() if v == "Orientation"), None
                )
                if orientation_key and orientation_key in exif:
                    orientation = exif[orientation_key]
                    if orientation == 3:
                        img = img.rotate(180, expand=True)
                    elif orientation == 6:
                        img = img.rotate(270, expand=True)
                    elif orientation == 8:
                        img = img.rotate(90, expand=True)

            w, h = img.size
            if w > MAX_IMAGE_DIMENSION or h > MAX_IMAGE_DIMENSION:
                ratio = min(MAX_IMAGE_DIMENSION / w, MAX_IMAGE_DIMENSION / h)
                new_w, new_h = int(w * ratio), int(h * ratio)
                logger.info(f"Downsizing image from {w}x{h} to {new_w}x{new_h}")
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                w, h = new_w, new_h

            if img.mode in ("RGBA", "P"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "RGBA":
                    background.paste(img, mask=img.split()[3])
                else:
                    background.paste(img)
                img = background

            if img.mode != "RGB":
                img = img.convert("RGB")

            out_io = io.BytesIO()
            img.save(out_io, format="JPEG", quality=JPEG_QUALITY)
            compressed = out_io.getvalue()
            
            logger.debug(f"Compressed image from {len(image_bytes)} to {len(compressed)} bytes.")
            return compressed, "image/jpeg", w, h

    except Exception as e:
        logger.warning(f"Image compression failed, using original bytes: {e}")
        return image_bytes, content_type, 0, 0


SYSTEM_PROMPT = """You are a cloud architecture diagram analyzer. Your job is to examine an architecture diagram image and extract EVERY cloud service shown. Connect them to their canonical Azure service equivalent.
You MUST respond ONLY with a raw JSON object in the exact schema specified below. Do NOT wrap the JSON in markdown code blocks. Just return the JSON object directly.

RULES:
1. Identify all cloud services visible in the diagram.
2. Detect the source cloud provider (aws or gcp).
3. Group services into logical architecture zones (e.g., "Networking", "Compute", "Database", "Security").
4. For each service, map it directly to its target AZURE equivalent. Calculate confidence (0.0 to 1.0) on this mapping.

REQUIRED JSON SCHEMA TEMPLATE:
{
  "diagram_type": "<short description>",
  "source_provider": "aws",
  "target_provider": "azure",
  "architecture_patterns": ["multi-AZ", "serverless", "microservices"],
  "services_detected": 1,
  "zones": [
    {
      "name": "Networking",
      "number": 1,
      "services": [
         {
             "name": "Amazon VPC",
             "short_name": "VPC",
             "role": "Isolated network environment",
             "detection_confidence": 0.95
         }
      ]
    }
  ],
  "mappings": [
    {
       "source_service": {
           "name": "Amazon VPC",
           "short_name": "VPC",
           "category": "Networking",
           "role": "Isolated network environment"
       },
       "target_service": "Virtual Network (VNet)",
       "confidence": 0.95,
       "category": "Networking",
       "description": "Azure Virtual Network is the equivalent to AWS VPC."
    }
  ],
  "warnings": [
    {
       "type": "potential_mismatch",
       "message": "Warning messages..."
    }
  ],
  "service_connections": [
     {"from": "Amazon API Gateway", "to": "AWS Lambda", "type": "HTTPS/Trigger"}
  ],
  "confidence_summary": {
     "high": 1,
     "medium": 0,
     "low": 0,
     "average": 0.95,
     "methodology": "AI-generated mapping directly from GPT-4o multimodal parsing"
  }
}
"""

def analyze_image(image_bytes: bytes, content_type: str = "image/png") -> Dict[str, Any]:
    """
    Analyze a cloud architecture diagram image using GPT-4o vision directly.
    """
    compressed_bytes, compressed_type, img_w, img_h = compress_image(image_bytes, content_type)
    
    if isinstance(compressed_bytes, str):
        compressed_bytes = compressed_bytes.encode("utf-8")

    cache_key = hashlib.sha256(compressed_bytes).hexdigest()
    with _vision_cache_lock:
        cached = _vision_cache.get(cache_key)
    if cached is not None:
        logger.info("Vision cache HIT (key=%s…)", cache_key[:12])
        return cached

    b64_image = base64.b64encode(compressed_bytes).decode("utf-8")
    client = get_openai_client()

    logger.info("Sending base64 image to native GPT-4o vision analyzer (%d bytes, %dx%d)", len(compressed_bytes), img_w, img_h)

    response = openai_retry(client.chat.completions.create)(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": PROMPT_ARMOR + "\n\n" + SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{compressed_type};base64,{b64_image}",
                            "detail": "auto"
                        },
                    }
                ],
            }
        ],
        max_tokens=4000,
        temperature=0.0,
        timeout=60.0
    )

    try:
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content.replace("```json", "", 1)
        if content.startswith("```"):
            content = content.replace("```", "", 1)
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        result = json.loads(content)
        
        with _vision_cache_lock:
            _vision_cache[cache_key] = result
            
        return result
    except Exception as e:
        logger.error(f"Failed to parse GPT-4o output. Error: {e}")
        raise RuntimeError("GPT-4o vision did not return a valid JSON schema.") from e
