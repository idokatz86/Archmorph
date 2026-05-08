"""HTTP smoke for `archmorph run` against the FastAPI app (#660)."""

from __future__ import annotations

import atexit
import json
import os
import socket
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock

import requests
import uvicorn
from click.testing import CliRunner

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("ARCHMORPH_EXPORT_CAPABILITY_REQUIRED", "false")
os.environ.setdefault("ARCHMORPH_DISABLE_IAC_CLI_VALIDATION", "1")
os.environ.setdefault("ENVIRONMENT", "test")

REPO_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_DIR / "backend"
CLI_DIR = REPO_DIR / "cli"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))

import archmorph_cli  # noqa: E402
import usage_metrics  # noqa: E402
from auth import AuthProvider, User, UserTier, generate_session_token  # noqa: E402
from main import IMAGE_STORE, SESSION_STORE, app  # noqa: E402

try:
    atexit.unregister(usage_metrics._shutdown_flush)
except ValueError:
    pass


SMOKE_ANALYSIS = {
    "diagram_type": "AWS Architecture",
    "title": "CLI Run Smoke",
    "source_provider": "aws",
    "target_provider": "azure",
    "architecture_patterns": ["multi-AZ"],
    "services_detected": 3,
    "zones": [
        {
            "id": 1,
            "name": "Compute",
            "number": 1,
            "services": [
                {"aws": "EC2", "azure": "Azure Virtual Machines", "confidence": 0.92},
                {"aws": "S3", "azure": "Azure Blob Storage", "confidence": 0.95},
            ],
        }
    ],
    "mappings": [
        {"source_service": "EC2", "source_provider": "aws", "azure_service": "Azure Virtual Machines", "category": "Compute", "confidence": 0.92},
        {"source_service": "S3", "source_provider": "aws", "azure_service": "Azure Blob Storage", "category": "Storage", "confidence": 0.95},
        {"source_service": "CloudWatch", "source_provider": "aws", "azure_service": "Azure Monitor", "category": "Monitoring", "confidence": 0.9},
    ],
    "service_connections": [
        {"from": "EC2", "to": "S3", "protocol": "HTTPS", "type": "storage"},
        {"from": "CloudWatch", "to": "EC2", "protocol": "HTTPS", "type": "metrics"},
    ],
    "warnings": [],
    "confidence_summary": {"high": 3, "medium": 0, "low": 0, "average": 0.92},
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_server(port: int) -> tuple[uvicorn.Server, threading.Thread]:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            response = requests.get(f"http://127.0.0.1:{port}/api/health", timeout=1)
            if response.status_code == 200:
                return server, thread
        except requests.RequestException:
            time.sleep(0.1)
    server.should_exit = True
    thread.join(timeout=5)
    raise RuntimeError("test server did not become ready")


def _mock_completion_for_iac(messages, **kwargs):
    prompt = str(messages[-1]["content"])
    assert "Azure Virtual Machines" in prompt
    assert "Azure Blob Storage" in prompt
    if "bicep" in prompt.lower():
        content = """targetScope = 'subscription'
param location string = 'westeurope'
resource rg 'Microsoft.Resources/resourceGroups@2023-07-01' = {
  name: 'rg-cli-smoke-dev'
  location: location
}
"""
    else:
        content = """terraform {
  required_version = ">= 1.5"
}

resource "terraform_data" "main" {
  input = {
    name = "rg-cli-smoke-dev"
  }
}
"""
    return MagicMock(choices=[MagicMock(message=MagicMock(content=content))], _truncated=False)


def _cli_smoke_token() -> str:
    user = User(
        id="cli-smoke-user",
        email="cli-smoke@example.com",
        provider=AuthProvider.GITHUB,
        tier=UserTier.TEAM,
        tenant_id="tenant-cli-smoke",
    )
    return generate_session_token(user)


def test_archmorph_run_smokes_over_http(monkeypatch, tmp_path):
    import routers.diagrams as diagrams_router
    import iac_generator

    SESSION_STORE.clear()
    IMAGE_STORE.clear()
    monkeypatch.setattr(diagrams_router, "classify_image", lambda *_args, **_kwargs: {
        "is_architecture_diagram": True,
        "confidence": 0.99,
        "image_type": "architecture_diagram",
        "reason": "CLI smoke",
    })
    monkeypatch.setattr(diagrams_router, "analyze_image", lambda *_args, **_kwargs: dict(SMOKE_ANALYSIS))
    monkeypatch.setattr(iac_generator, "cached_chat_completion", _mock_completion_for_iac)

    port = _free_port()
    server, thread = _start_server(port)
    try:
        diagram = tmp_path / "aws.png"
        diagram.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 100)
        out_dir = tmp_path / "infra"

        result = CliRunner().invoke(
            archmorph_cli.cli,
            [
                "--api-url",
                f"http://127.0.0.1:{port}",
                "--token",
                _cli_smoke_token(),
                "run",
                "--diagram",
                str(diagram),
                "--target-rg",
                "rg-cli-smoke-dev",
                "--emit",
                "terraform,bicep,alz-svg,cost",
                "--out",
                str(out_dir),
            ],
        )

        assert result.exit_code == 0, result.output
        analysis = json.loads((out_dir / "analysis.json").read_text(encoding="utf-8"))
        assert analysis["cli_run"]["target_resource_group"] == "rg-cli-smoke-dev"
        assert analysis["iac_parameters"]["project_name"] == "cli-smoke-dev"
        assert 'resource "terraform_data"' in (out_dir / "terraform" / "main.tf").read_text(encoding="utf-8")
        assert "targetScope" in (out_dir / "bicep" / "main.bicep").read_text(encoding="utf-8")
        ET.fromstring((out_dir / "alz.svg").read_text(encoding="utf-8"))
        cost = json.loads((out_dir / "cost-estimate.json").read_text(encoding="utf-8"))
        assert cost["currency"] == "USD"
        summary = json.loads((out_dir / "run-summary.json").read_text(encoding="utf-8"))
        assert summary["artifacts"]["analysis"].endswith("analysis.json")
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        SESSION_STORE.clear()
        IMAGE_STORE.clear()
