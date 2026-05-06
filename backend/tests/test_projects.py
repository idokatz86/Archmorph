import copy
import io
from unittest.mock import patch

import pytest

from routers.shared import DIAGRAM_PROJECT_STORE, IMAGE_STORE, PROJECT_STORE, SESSION_STORE


MOCK_ANALYSIS = {
    "diagram_type": "AWS Architecture",
    "source_provider": "aws",
    "target_provider": "azure",
    "services_detected": 2,
    "zones": [
        {"id": 1, "name": "Compute", "services": [{"aws": "Amazon EC2", "azure": "Azure Virtual Machines", "confidence": 0.95}]},
    ],
    "mappings": [
        {"source_service": "Amazon EC2", "source_provider": "aws", "azure_service": "Azure Virtual Machines", "confidence": 0.95},
        {"source_service": "Amazon S3", "source_provider": "aws", "azure_service": "Azure Blob Storage", "confidence": 0.91},
    ],
    "service_connections": [{"from": "Amazon EC2", "to": "Amazon S3", "protocol": "HTTPS"}],
    "warnings": [],
    "confidence_summary": {"high": 2, "medium": 0, "low": 0, "average": 0.93},
}


@pytest.fixture(autouse=True)
def clean_project_state():
    SESSION_STORE.clear()
    IMAGE_STORE.clear()
    PROJECT_STORE.clear()
    DIAGRAM_PROJECT_STORE.clear()
    yield
    SESSION_STORE.clear()
    IMAGE_STORE.clear()
    PROJECT_STORE.clear()
    DIAGRAM_PROJECT_STORE.clear()


def _upload(test_client, project_id="project-241", filename="arch.png"):
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    response = test_client.post(
        f"/api/projects/{project_id}/diagrams",
        files={"file": (filename, io.BytesIO(content), "image/png")},
    )
    assert response.status_code == 200
    return response.json()


def _analyze(test_client, diagram_id, analysis=None):
    analysis = analysis or MOCK_ANALYSIS
    with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(analysis)):
        response = test_client.post(f"/api/diagrams/{diagram_id}/analyze")
    assert response.status_code == 200
    return response.json()


def test_upload_registers_diagram_under_project(test_client):
    uploaded = _upload(test_client, project_id="project-241")

    assert uploaded["project_id"] == "project-241"

    response = test_client.get("/api/projects/project-241")
    assert response.status_code == 200
    project = response.json()
    assert project["project_id"] == "project-241"
    assert project["diagram_ids"] == [uploaded["diagram_id"]]
    assert project["diagrams"][0]["status"] == "uploaded"
    assert project["diagrams"][0]["filename"] == "arch.png"


def test_project_analysis_merges_analyzed_diagrams(test_client):
    first = _upload(test_client, project_id="project-241", filename="compute.png")
    second = _upload(test_client, project_id="project-241", filename="data.png")

    _analyze(test_client, first["diagram_id"])
    second_analysis = copy.deepcopy(MOCK_ANALYSIS)
    second_analysis["mappings"] = [
        {"source_service": "Amazon S3", "source_provider": "aws", "azure_service": "Azure Blob Storage", "confidence": 0.99},
        {"source_service": "Amazon RDS", "source_provider": "aws", "azure_service": "Azure SQL Database", "confidence": 0.86},
    ]
    second_analysis["services_detected"] = 2
    _analyze(test_client, second["diagram_id"], second_analysis)

    response = test_client.get("/api/projects/project-241/analysis")

    assert response.status_code == 200
    combined = response.json()
    assert combined["project_id"] == "project-241"
    assert combined["combined"] is True
    assert combined["services_detected"] == 3
    assert combined["source_diagram_ids"] == sorted([first["diagram_id"], second["diagram_id"]])
    s3 = [m for m in combined["mappings"] if m["source_service"] == "Amazon S3"][0]
    assert s3["confidence"] == 0.99
    assert s3["source_diagram_ids"] == sorted([first["diagram_id"], second["diagram_id"]])
    assert any(link["service"] == "Amazon S3" for link in combined["cross_diagram_links"])


def test_project_generate_uses_combined_analysis(test_client):
    first = _upload(test_client, project_id="project-241")
    _analyze(test_client, first["diagram_id"])

    with patch("routers.projects.generate_iac_code", return_value='resource "azurerm_resource_group" "rg" {}') as generate:
        response = test_client.post("/api/projects/project-241/generate?format=terraform")

    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == "project-241"
    assert data["format"] == "terraform"
    assert "azurerm_resource_group" in data["code"]
    assert generate.call_args.kwargs["analysis"]["combined"] is True


def test_project_analysis_requires_analyzed_diagrams(test_client):
    _upload(test_client, project_id="project-241")

    response = test_client.get("/api/projects/project-241/analysis")

    assert response.status_code == 404