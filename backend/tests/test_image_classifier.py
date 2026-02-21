"""
Tests for image_classifier.py — Architecture diagram pre-check.
"""

import json
from unittest.mock import patch, MagicMock

# ─── Helper: build a mock OpenAI response ───
def _mock_response(content: str):
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ─────────────────────────────────────────────
# 1. Accept — valid architecture diagram
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_accepts_architecture_diagram(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": True,
            "confidence": 0.97,
            "image_type": "AWS cloud architecture diagram",
            "reason": "Image shows AWS services including EC2, RDS, and S3 in a multi-AZ deployment.",
        })
    )

    result = classify_image(b"fake-image-bytes", "image/png")

    assert result["is_architecture_diagram"] is True
    assert result["confidence"] >= 0.90
    assert "architecture" in result["image_type"].lower()


# ─────────────────────────────────────────────
# 2. Reject — personal photo
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_rejects_personal_photo(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": False,
            "confidence": 0.99,
            "image_type": "personal photograph of a person",
            "reason": "Image shows a person posing for a portrait photo, not a technical diagram.",
        })
    )

    result = classify_image(b"fake-selfie-bytes", "image/jpeg")

    assert result["is_architecture_diagram"] is False
    assert result["confidence"] >= 0.90
    assert "person" in result["image_type"].lower()


# ─────────────────────────────────────────────
# 3. Reject — meme
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_rejects_meme(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": False,
            "confidence": 0.95,
            "image_type": "internet meme",
            "reason": "Image is a meme with text overlay, not a technical diagram.",
        })
    )

    result = classify_image(b"meme-bytes", "image/png")

    assert result["is_architecture_diagram"] is False
    assert result["confidence"] >= 0.90


# ─────────────────────────────────────────────
# 4. Accept — hand-drawn whiteboard
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_accepts_whiteboard_diagram(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": True,
            "confidence": 0.82,
            "image_type": "hand-drawn architecture sketch on whiteboard",
            "reason": "Image shows a whiteboard with servers, databases, and arrows depicting a system architecture.",
        })
    )

    result = classify_image(b"whiteboard-bytes", "image/jpeg")

    assert result["is_architecture_diagram"] is True
    assert result["confidence"] >= 0.80


# ─────────────────────────────────────────────
# 5. Accept — GCP diagram
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_accepts_gcp_diagram(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": True,
            "confidence": 0.96,
            "image_type": "GCP cloud architecture diagram",
            "reason": "Image shows Google Cloud services including Compute Engine, Cloud SQL, and Cloud Load Balancing.",
        })
    )

    result = classify_image(b"gcp-bytes", "image/png")

    assert result["is_architecture_diagram"] is True


# ─────────────────────────────────────────────
# 6. Reject — nature photo
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_rejects_nature_photo(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": False,
            "confidence": 0.99,
            "image_type": "landscape photograph",
            "reason": "Image shows a mountain landscape, not a technical diagram.",
        })
    )

    result = classify_image(b"nature-bytes", "image/jpeg")

    assert result["is_architecture_diagram"] is False


# ─────────────────────────────────────────────
# 7. Reject — food photo
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_rejects_food_photo(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": False,
            "confidence": 0.98,
            "image_type": "food photograph",
            "reason": "Image shows a plate of food, not a technical diagram.",
        })
    )

    result = classify_image(b"food-bytes", "image/jpeg")

    assert result["is_architecture_diagram"] is False


# ─────────────────────────────────────────────
# 8. JSON parse error — fail-open
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_fail_open_on_parse_error(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        "This is not valid JSON at all!!!"
    )

    result = classify_image(b"bad-response-bytes", "image/png")

    # Should fail-closed: reject on parse error (issue #73)
    assert result["is_architecture_diagram"] is False
    assert result["confidence"] == 0.0
    assert "parse error" in result["reason"].lower()


# ─────────────────────────────────────────────
# 9. JSON wrapped in ```json block
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_handles_json_code_block(mock_client):
    from image_classifier import classify_image

    wrapped = '```json\n' + json.dumps({
        "is_architecture_diagram": True,
        "confidence": 0.91,
        "image_type": "network topology diagram",
        "reason": "Shows network components.",
    }) + '\n```'

    mock_client.return_value.chat.completions.create.return_value = _mock_response(wrapped)

    result = classify_image(b"code-block-bytes", "image/png")

    assert result["is_architecture_diagram"] is True
    assert result["confidence"] == 0.91


# ─────────────────────────────────────────────
# 10. Default content type
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_default_content_type(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": True,
            "confidence": 0.88,
            "image_type": "cloud architecture diagram",
            "reason": "Valid diagram.",
        })
    )

    # Call without explicit content_type
    result = classify_image(b"some-bytes")

    assert result["is_architecture_diagram"] is True
    # Verify call was made with image/png default
    call_args = mock_client.return_value.chat.completions.create.call_args
    user_content = call_args[1]["messages"][1]["content"]
    image_url = [c for c in user_content if c.get("type") == "image_url"][0]
    assert "image/png" in image_url["image_url"]["url"]


# ─────────────────────────────────────────────
# 11. Uses low detail for classification
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_uses_low_detail(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": True,
            "confidence": 0.90,
            "image_type": "diagram",
            "reason": "Valid.",
        })
    )

    classify_image(b"test-bytes", "image/png")

    call_args = mock_client.return_value.chat.completions.create.call_args
    user_content = call_args[1]["messages"][1]["content"]
    image_url = [c for c in user_content if c.get("type") == "image_url"][0]
    assert image_url["image_url"]["detail"] == "low"


# ─────────────────────────────────────────────
# 12. Reject — screenshot of chat app
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_rejects_chat_screenshot(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": False,
            "confidence": 0.94,
            "image_type": "screenshot of a messaging application",
            "reason": "Image shows a chat conversation, not a technical diagram.",
        })
    )

    result = classify_image(b"chat-screenshot", "image/png")

    assert result["is_architecture_diagram"] is False


# ─────────────────────────────────────────────
# 13. Reject — business pie chart
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_rejects_business_chart(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": False,
            "confidence": 0.88,
            "image_type": "business pie chart",
            "reason": "Image shows revenue distribution chart, not a system architecture.",
        })
    )

    result = classify_image(b"chart-bytes", "image/png")

    assert result["is_architecture_diagram"] is False


# ─────────────────────────────────────────────
# 14. Accept — Kubernetes deployment diagram
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_accepts_k8s_diagram(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": True,
            "confidence": 0.93,
            "image_type": "Kubernetes deployment architecture",
            "reason": "Image shows K8s pods, services, and ingress controllers.",
        })
    )

    result = classify_image(b"k8s-bytes", "image/png")

    assert result["is_architecture_diagram"] is True


# ─────────────────────────────────────────────
# 15. Accept — data pipeline diagram
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_accepts_data_pipeline(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": True,
            "confidence": 0.89,
            "image_type": "data pipeline architecture diagram",
            "reason": "Image shows ETL pipeline with data sources, transformations, and sinks.",
        })
    )

    result = classify_image(b"pipeline-bytes", "image/png")

    assert result["is_architecture_diagram"] is True


# ─────────────────────────────────────────────
# 16. Confidence normalization (missing fields)
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_handles_missing_fields(mock_client):
    from image_classifier import classify_image

    # Minimal response — missing confidence and reason
    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": True,
        })
    )

    result = classify_image(b"minimal-bytes", "image/png")

    assert result["is_architecture_diagram"] is True
    assert result["confidence"] == 0.5  # default
    assert result["image_type"] == "unknown"
    assert result["reason"] == ""


# ─────────────────────────────────────────────
# 17. API key auth path
# ─────────────────────────────────────────────
@patch("openai_client.AZURE_OPENAI_KEY", "test-key-123")
@patch("openai_client.AzureOpenAI")
def test_classify_uses_api_key_auth(mock_azure_cls):
    from openai_client import get_openai_client, reset_client
    reset_client()

    get_openai_client()

    mock_azure_cls.assert_called_once()
    call_kwargs = mock_azure_cls.call_args[1]
    assert call_kwargs["api_key"] == "test-key-123"
    reset_client()


# ─────────────────────────────────────────────
# 18. Reject — blank / corrupted image
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_rejects_blank_image(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": False,
            "confidence": 0.92,
            "image_type": "blank or corrupted image",
            "reason": "Image appears to be blank or contains no discernible content.",
        })
    )

    result = classify_image(b"blank-bytes", "image/png")

    assert result["is_architecture_diagram"] is False


# ─────────────────────────────────────────────
# 19. Accept — multi-cloud hybrid diagram
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_accepts_multi_cloud_diagram(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": True,
            "confidence": 0.94,
            "image_type": "multi-cloud hybrid architecture diagram",
            "reason": "Image shows services spanning AWS and on-premises data center with VPN connections.",
        })
    )

    result = classify_image(b"hybrid-bytes", "image/png")

    assert result["is_architecture_diagram"] is True
    assert result["confidence"] >= 0.90


# ─────────────────────────────────────────────
# 20. Reject — org chart (people)
# ─────────────────────────────────────────────
@patch("image_classifier.get_openai_client")
def test_classify_rejects_org_chart(mock_client):
    from image_classifier import classify_image

    mock_client.return_value.chat.completions.create.return_value = _mock_response(
        json.dumps({
            "is_architecture_diagram": False,
            "confidence": 0.87,
            "image_type": "organizational chart",
            "reason": "Image shows a company org chart with employee names and titles, not a system architecture.",
        })
    )

    result = classify_image(b"org-chart-bytes", "image/png")

    assert result["is_architecture_diagram"] is False
