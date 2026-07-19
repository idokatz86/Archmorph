"""Contract tests for the streamed analysis-report artifact."""

from export_capabilities import issue_export_capability
from routers.shared import EXPORT_CAPABILITY_STORE, SESSION_STORE


DIAGRAM_ID = "report-contract-diagram"


def test_report_export_is_real_pdf_and_rotates_capability(test_client, monkeypatch):
    monkeypatch.setenv("ARCHMORPH_EXPORT_CAPABILITY_REQUIRED", "true")
    SESSION_STORE[DIAGRAM_ID] = {
        "title": "Contract Architecture",
        "source_provider": "aws",
        "target_provider": "azure",
        "mappings": [
            {
                "source_service": "Lambda",
                "azure_service": "Azure Functions",
                "confidence": 0.95,
                "category": "Compute",
            }
        ],
        "zones": [],
        "warnings": [],
    }
    token = issue_export_capability(DIAGRAM_ID)

    try:
        response = test_client.get(
            f"/api/diagrams/{DIAGRAM_ID}/report?format=pdf",
            headers={"X-Export-Capability": token},
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/pdf")
        assert response.headers["content-disposition"].endswith('.pdf"')
        assert len(response.headers["x-artifact-sha256"]) == 64
        assert response.headers["x-export-capability-next"]
        assert response.content.startswith(b"%PDF-")

        replay = test_client.get(
            f"/api/diagrams/{DIAGRAM_ID}/report?format=pdf",
            headers={"X-Export-Capability": token},
        )
        assert replay.status_code == 401
    finally:
        SESSION_STORE.delete(DIAGRAM_ID)
        EXPORT_CAPABILITY_STORE.clear()
