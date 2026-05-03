"""Regression tests for exportable session identifier entropy (#610)."""

from __future__ import annotations

import io
import re
from pathlib import Path

from routers.shared import generate_session_id


URL_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{22,}$")


def _assert_high_entropy_id(identifier: str, prefix: str) -> None:
    assert identifier.startswith(f"{prefix}-")
    token = identifier.removeprefix(f"{prefix}-")
    assert URL_SAFE_TOKEN_RE.fullmatch(token), identifier
    assert not re.fullmatch(r"[0-9a-f]{6,8}", token), identifier


def test_generate_session_id_uses_url_safe_high_entropy_token():
    identifier = generate_session_id("diag")
    _assert_high_entropy_id(identifier, "diag")


def test_upload_diagram_mints_high_entropy_diag_id(test_client):
    response = test_client.post(
        "/api/projects/proj-001/diagrams",
        files={"file": ("test.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 50), "image/png")},
    )

    assert response.status_code == 200
    _assert_high_entropy_id(response.json()["diagram_id"], "diag")


def test_sample_analysis_mints_high_entropy_sample_id(test_client):
    response = test_client.post("/api/samples/aws-iaas/analyze")

    assert response.status_code == 200
    _assert_high_entropy_id(response.json()["diagram_id"], "sample-aws-iaas")


def test_infrastructure_import_mints_high_entropy_import_id(test_client, monkeypatch):
    import routers.infra_import as infra_routes

    def fake_parse_infrastructure(content, fmt, diagram_id):
        return {
            "diagram_id": diagram_id,
            "source_format": fmt.value,
            "services_detected": 0,
            "source_provider": "aws",
            "mappings": [],
            "zones": [],
            "service_connections": [],
            "confidence_summary": {"high": 0, "medium": 0, "low": 0, "average": 0},
            "architecture_patterns": [],
        }

    monkeypatch.setattr(infra_routes, "parse_infrastructure", fake_parse_infrastructure)

    response = test_client.post(
        "/api/import/infrastructure",
        json={
            "content": "resource \"aws_s3_bucket\" \"example\" {}",
            "format": "terraform_hcl",
            "filename": "main.tf",
        },
    )

    assert response.status_code == 200
    _assert_high_entropy_id(response.json()["diagram_id"], "import")


def test_exportable_session_routes_do_not_use_truncated_uuid_ids():
    repo_root = Path(__file__).resolve().parents[1]
    checked_files = [
        repo_root / "routers" / "diagrams.py",
        repo_root / "routers" / "samples.py",
        repo_root / "routers" / "infra_import.py",
    ]
    forbidden = re.compile(r"uuid\.uuid4\(\)\.hex\[:8\]|token_urlsafe\([468]\)")

    offenders = [
        str(path.relative_to(repo_root))
        for path in checked_files
        if forbidden.search(path.read_text(encoding="utf-8"))
    ]

    assert not offenders, f"Weak exportable session ID generation in: {offenders}"