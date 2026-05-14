from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"
MCP_GATEWAY_DOCKERFILE = REPO_ROOT / "mcp-gateway" / "Dockerfile"


def test_backend_and_mcp_gateway_images_use_pinned_python_digest():
    backend_contents = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    mcp_contents = MCP_GATEWAY_DOCKERFILE.read_text(encoding="utf-8")

    assert "python:3.12.12-slim-bookworm@sha256:" in backend_contents
    assert "python:3.12.12-slim-bookworm@sha256:" in mcp_contents


def test_mcp_gateway_image_runs_non_root_and_has_healthcheck():
    contents = MCP_GATEWAY_DOCKERFILE.read_text(encoding="utf-8")

    assert "USER appuser" in contents
    assert "HEALTHCHECK" in contents
