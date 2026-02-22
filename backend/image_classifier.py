"""
Archmorph Image Classifier — GPT-4o pre-check for architecture diagrams.

Validates that an uploaded image is actually a cloud/IT architecture diagram
before running the full analysis pipeline. Rejects personal photos, memes,
screenshots of non-technical content, etc.
"""

import base64
import json
import logging
from typing import Any, Dict

from openai_client import get_openai_client, AZURE_OPENAI_DEPLOYMENT, openai_retry
from prompt_guard import PROMPT_ARMOR

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Classification prompt
# ─────────────────────────────────────────────────────────────
CLASSIFICATION_PROMPT = """You are an image classification gate for a cloud architecture translation tool.

Your ONLY job is to determine whether the uploaded image is a valid technical architecture diagram that can be analyzed for cloud service migration.

ACCEPT (is_architecture_diagram = true):
- Cloud architecture diagrams (AWS, GCP, Azure, multi-cloud)
- Network topology diagrams
- Infrastructure diagrams showing servers, databases, load balancers, etc.
- System design diagrams with technical components
- Data flow / pipeline diagrams
- Deployment architecture diagrams
- Microservices architecture diagrams
- Hand-drawn or whiteboard architecture sketches with technical components
- UML diagrams showing system architecture
- Kubernetes / container orchestration diagrams

REJECT (is_architecture_diagram = false):
- Personal photos (people, selfies, portraits)
- Screenshots of code editors, chat apps, social media
- Memes, jokes, or entertainment images
- Nature, landscape, or travel photos
- Food, animals, or everyday objects
- Business charts (pie charts, bar charts) without architecture content
- Blank or corrupted images
- Marketing materials, flyers, or advertisements
- Org charts (people hierarchy, not systems)
- Any image that does NOT depict a technical system architecture

Respond ONLY with valid JSON:
{
  "is_architecture_diagram": true | false,
  "confidence": 0.0 to 1.0,
  "image_type": "<brief description of what the image actually shows>",
  "reason": "<one sentence explaining why it was accepted or rejected>"
}
""" + PROMPT_ARMOR


def classify_image(image_bytes: bytes, content_type: str = "image/png") -> Dict[str, Any]:
    """
    Classify whether an image is a valid architecture diagram.

    Args:
        image_bytes: Raw image bytes (PNG, JPEG, etc.)
        content_type: MIME type of the image

    Returns:
        dict with keys:
            - is_architecture_diagram (bool)
            - confidence (float 0-1)
            - image_type (str)
            - reason (str)
    """
    # Compress for classification (low detail is fine)
    from vision_analyzer import compress_image
    compressed_bytes, compressed_type, _w, _h = compress_image(image_bytes, content_type)

    b64_image = base64.b64encode(compressed_bytes).decode("utf-8")
    media_type = compressed_type

    client = get_openai_client()

    logger.info(
        "Classifying image (%d bytes, %s) — architecture diagram pre-check",
        len(compressed_bytes),
        media_type,
    )

    response = openai_retry(client.chat.completions.create)(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": CLASSIFICATION_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Is this image a valid cloud or IT architecture diagram? Classify it.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{b64_image}",
                            "detail": "low",  # low detail is sufficient for classification
                        },
                    },
                ],
            },
        ],
        max_tokens=256,
        temperature=0.0,
    )

    raw_text = response.choices[0].message.content.strip()
    logger.info("Classification response: %s", raw_text[:200])

    # Parse JSON from response
    json_text = raw_text
    if "```json" in json_text:
        json_text = json_text.split("```json", 1)[1]
        json_text = json_text.split("```", 1)[0]
    elif "```" in json_text:
        json_text = json_text.split("```", 1)[1]
        json_text = json_text.split("```", 1)[0]

    try:
        result = json.loads(json_text.strip())
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse classification JSON: %s\nRaw: %s", exc, raw_text)
        # On parse failure, reject (fail-closed) to avoid processing non-diagrams
        return {
            "is_architecture_diagram": False,
            "confidence": 0.0,
            "image_type": "unknown",
            "reason": "Classification parse error — rejecting for safety",
        }

    # Normalize result
    return {
        "is_architecture_diagram": bool(result.get("is_architecture_diagram", True)),
        "confidence": float(result.get("confidence", 0.5)),
        "image_type": str(result.get("image_type", "unknown")),
        "reason": str(result.get("reason", "")),
    }
