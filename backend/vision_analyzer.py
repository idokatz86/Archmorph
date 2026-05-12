"""
Archmorph Vision Analyzer — Direct GPT-4o powered diagram analysis.
Upgraded to Native Multimodal (Issue #417).
"""
import base64
import hashlib
import io
import json
import logging
import os
import time
from typing import Any, Dict, Tuple

from PIL import Image
import threading

from utils.chat_coercion import coerce_to_str_list

from openai_client import get_openai_client, AZURE_OPENAI_DEPLOYMENT, openai_retry
from observability import increment_counter, record_histogram, set_gauge
from prompt_guard import PROMPT_ARMOR
from session_store import get_store

logger = logging.getLogger(__name__)

# Maximum image dimension for GPT-4o vision (keeps quality while reducing tokens)
MAX_IMAGE_DIMENSION = 2048
JPEG_QUALITY = 85

# PDF rasterization (Issue: GPT-4o rejects application/pdf data URLs).
# Render at ~150 DPI so text in architecture diagrams stays legible after the
# downstream 2048px clamp. Cap pages to bound work and tokens for malicious
# or oversized uploads.
MAX_PDF_PAGES = 10
PDF_RENDER_DPI = 150
_PDF_PAGE_SEPARATOR_PX = 8

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("Invalid %s=%r; using default %d", name, os.getenv(name), default)
        return default


def _vision_cache_settings() -> tuple[int, int]:
    return (
        max(1, _env_int("VISION_CACHE_MAXSIZE", 500)),
        max(1, _env_int("VISION_CACHE_TTL_SECONDS", 3600)),
    )


VISION_CACHE_MAXSIZE, VISION_CACHE_TTL_SECONDS = _vision_cache_settings()

# Thread-safe cache for vision results. Uses the shared store abstraction so
# Redis-configured deployments can share hits across workers/replicas.
_vision_cache = get_store("vision_cache", maxsize=VISION_CACHE_MAXSIZE, ttl=VISION_CACHE_TTL_SECONDS)
_vision_cache_lock = threading.Lock()

VISION_CACHE_METRIC = "archmorph.vision.cache"
VISION_LATENCY_METRIC = "archmorph.vision.latency_ms"
VISION_PROMPT_HASH_METRIC = "archmorph.vision.prompt_hash"


def _is_pdf(image_bytes: bytes, content_type: str) -> bool:
    """Return True if the payload looks like a PDF.

    Trusts the magic bytes over the declared content_type because browsers
    sometimes send PDFs as application/octet-stream and our IMAGE_STORE
    persists whatever the client claimed at upload time.
    """
    if content_type == "application/pdf":
        return True
    return len(image_bytes) >= 5 and image_bytes[:5] == b"%PDF-"


def _rasterize_pdf_to_png(pdf_bytes: bytes) -> bytes:
    """Render a PDF to a single PNG image suitable for vision analysis.

    Multi-page PDFs are stitched vertically with a thin white separator so
    the existing single-image vision pipeline keeps working unchanged.
    Page count is capped at ``MAX_PDF_PAGES`` to bound work.

    Raises ``ValueError`` if the PDF cannot be opened or has no pages.
    """
    # Imported lazily so the rest of the module (and its tests) can import
    # without paying pypdfium2's startup cost or requiring the dep on
    # non-PDF code paths.
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
    except Exception as exc:  # pdfium raises a variety of low-level errors
        raise ValueError(f"Unable to open PDF: {exc}") from exc

    n_pages = len(pdf)
    if n_pages == 0:
        raise ValueError("PDF has no pages")
    if n_pages > MAX_PDF_PAGES:
        logger.warning(
            "PDF has %d pages — only first %d will be rasterized",
            n_pages, MAX_PDF_PAGES,
        )
        n_pages = MAX_PDF_PAGES

    scale = PDF_RENDER_DPI / 72.0  # PDFium's base unit is 72 DPI
    pages: list[Image.Image] = []
    for i in range(n_pages):
        page = pdf[i]
        pil_page = page.render(scale=scale).to_pil()
        if pil_page.mode != "RGB":
            pil_page = pil_page.convert("RGB")
        pages.append(pil_page)

    if len(pages) == 1:
        combined = pages[0]
    else:
        width = max(p.width for p in pages)
        height = sum(p.height for p in pages) + _PDF_PAGE_SEPARATOR_PX * (len(pages) - 1)
        combined = Image.new("RGB", (width, height), (255, 255, 255))
        y = 0
        for p in pages:
            x = (width - p.width) // 2
            combined.paste(p, (x, y))
            y += p.height + _PDF_PAGE_SEPARATOR_PX

    buf = io.BytesIO()
    combined.save(buf, format="PNG", optimize=True)
    logger.info(
        "Rasterized PDF: %d page(s) → PNG %dx%d (%d bytes)",
        n_pages, combined.width, combined.height, buf.tell(),
    )
    return buf.getvalue()


def compress_image(image_bytes: bytes, content_type: str = "image/png") -> Tuple[bytes, str, int, int]:
    """
    Ensures image is max 2048px (maintaining aspect ratio), converting it to JPEG.
    Returns (compressed_bytes, new_content_type, width, height)
    """
    # GPT-4o vision rejects application/pdf data URLs — rasterize first so
    # the rest of the pipeline sees a normal raster image.
    if _is_pdf(image_bytes, content_type):
        try:
            image_bytes = _rasterize_pdf_to_png(image_bytes)
            content_type = "image/png"
        except ValueError as exc:
            logger.error("PDF rasterization failed: %s", exc)
            raise

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


def _vision_prompt() -> str:
    return PROMPT_ARMOR + "\n\n" + SYSTEM_PROMPT


def _compute_vision_prompt_hash(model_name: str) -> str:
    source = _vision_prompt() + model_name
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]


def _compute_vision_cache_key(compressed_bytes: bytes, model_name: str, prompt_hash: str) -> str:
    digest = hashlib.sha256()
    digest.update(compressed_bytes)
    digest.update(b"\0")
    digest.update(model_name.encode("utf-8"))
    digest.update(b"\0")
    digest.update(prompt_hash.encode("utf-8"))
    return digest.hexdigest()


def _emit_prompt_hash_metric(model_name: str, prompt_hash: str) -> None:
    set_gauge(
        VISION_PROMPT_HASH_METRIC,
        1.0,
        tags={"model": model_name, "prompt_hash": prompt_hash},
    )


def _record_vision_latency(start_time: float, cache_hit: bool, model_name: str, prompt_hash: str) -> None:
    record_histogram(
        VISION_LATENCY_METRIC,
        (time.perf_counter() - start_time) * 1000,
        tags={
            "cache_hit": str(cache_hit).lower(),
            "model": model_name,
            "prompt_hash": prompt_hash,
        },
    )


VISION_PROMPT_HASH = _compute_vision_prompt_hash(AZURE_OPENAI_DEPLOYMENT)
_emit_prompt_hash_metric(AZURE_OPENAI_DEPLOYMENT, VISION_PROMPT_HASH)

def analyze_image(image_bytes: bytes, content_type: str = "image/png") -> Dict[str, Any]:
    """
    Analyze a cloud architecture diagram image using GPT-4o vision directly.
    """
    start_time = time.perf_counter()
    compressed_bytes, compressed_type, img_w, img_h = compress_image(image_bytes, content_type)
    
    if isinstance(compressed_bytes, str):
        compressed_bytes = compressed_bytes.encode("utf-8")

    model_name = AZURE_OPENAI_DEPLOYMENT
    prompt_hash = _compute_vision_prompt_hash(model_name)
    _emit_prompt_hash_metric(model_name, prompt_hash)

    cache_key = _compute_vision_cache_key(compressed_bytes, model_name, prompt_hash)
    with _vision_cache_lock:
        cached = _vision_cache.get(cache_key)
    if cached is not None:
        logger.info("Vision cache HIT (key=%s…)", cache_key[:12])
        increment_counter(VISION_CACHE_METRIC, tags={"result": "hit", "model": model_name})
        _record_vision_latency(start_time, True, model_name, prompt_hash)
        return cached

    increment_counter(VISION_CACHE_METRIC, tags={"result": "miss", "model": model_name})

    b64_image = base64.b64encode(compressed_bytes).decode("utf-8")
    client = get_openai_client()

    logger.info("Sending base64 image to native GPT-4o vision analyzer (%d bytes, %dx%d)", len(compressed_bytes), img_w, img_h)

    response = openai_retry(client.chat.completions.create)(
        model=model_name,
        messages=[
            {"role": "system", "content": _vision_prompt()},
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

        # Vision prompt asks GPT for warnings as `{type, message}` objects, but
        # the React UI renders them inline (`<span>{w}</span>`). Flatten to
        # strings at the API boundary so a single misbehaving response cannot
        # crash the frontend with React error #31.
        if isinstance(result, dict) and "warnings" in result:
            result["warnings"] = coerce_to_str_list(result.get("warnings", []))

        with _vision_cache_lock:
            _vision_cache[cache_key] = result
            
        return result
    except Exception as e:
        logger.error(f"Failed to parse GPT-4o output. Error: {e}")
        raise RuntimeError("GPT-4o vision did not return a valid JSON schema.") from e
    finally:
        _record_vision_latency(start_time, False, model_name, prompt_hash)
