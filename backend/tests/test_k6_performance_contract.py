from pathlib import Path


K6_SCRIPT = Path(__file__).parent / "performance" / "api_load_test.js"


def test_k6_summary_exposes_endpoint_latency_breakdown():
    script = K6_SCRIPT.read_text(encoding="utf-8")

    assert "static_endpoint_latency_ms" in script
    assert "static_endpoint_p95_ms" in script
    assert "catalog_response_chars_p95" in script
    for endpoint_name in ("health", "services", "flags", "roadmap", "versions"):
        assert f"static_{endpoint_name}_latency" in script


def test_k6_requests_tag_static_endpoints():
    script = K6_SCRIPT.read_text(encoding="utf-8")

    assert "tags:" in script
    assert "endpoint:" in script
    assert "ep.name" in script
