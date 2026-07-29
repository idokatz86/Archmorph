"""Contract tests for the streamed analysis-report artifact."""

from auth import AuthProvider, User, generate_session_token
from export_capabilities import issue_export_capability_for_identity
from routers.shared import EXPORT_CAPABILITY_STORE, SESSION_STORE


DIAGRAM_ID = "report-contract-diagram"


def test_report_export_is_real_pdf_and_rotates_capability(test_client, monkeypatch):
    from database import SessionLocal
    from workspace_store import persist_analysis_state

    monkeypatch.setenv("ARCHMORPH_EXPORT_CAPABILITY_REQUIRED", "true")
    monkeypatch.setattr(
        "export_artifacts._upload_blob",
        lambda **kwargs: f"testblob://{kwargs['content_hash']}",
    )
    snapshot = {
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
    db = SessionLocal()
    try:
        persist_analysis_state(
            db,
            owner_user_id="report-owner",
            tenant_id="report-tenant",
            diagram_id=DIAGRAM_ID,
            snapshot=snapshot,
            session_store=SESSION_STORE,
            cache_required=True,
        )
    finally:
        db.close()
    user = User(
        id="report-owner",
        provider=AuthProvider.GITHUB,
        tenant_id="report-tenant",
    )
    headers = {
        "Authorization": f"Bearer {generate_session_token(user)}",
    }
    token = issue_export_capability_for_identity(
        DIAGRAM_ID,
        caller_owner_user_id="report-owner",
        tenant_id="report-tenant",
    )

    try:
        response = test_client.get(
            f"/api/diagrams/{DIAGRAM_ID}/report?format=pdf",
            headers={**headers, "X-Export-Capability": token},
        )

        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/pdf")
        assert response.headers["content-disposition"].endswith('.pdf"')
        assert len(response.headers["x-artifact-sha256"]) == 64
        assert response.headers["x-export-capability-next"]
        assert response.content.startswith(b"%PDF-")

        replay = test_client.get(
            f"/api/diagrams/{DIAGRAM_ID}/report?format=pdf",
            headers={**headers, "X-Export-Capability": token},
        )
        assert replay.status_code == 401
    finally:
        SESSION_STORE.delete(DIAGRAM_ID)
        EXPORT_CAPABILITY_STORE.clear()
