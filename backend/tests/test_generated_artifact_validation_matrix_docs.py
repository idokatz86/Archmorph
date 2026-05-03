"""Release documentation guardrails for generated artifact validation (#669)."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX = REPO_ROOT / "docs" / "GENERATED_ARTIFACT_VALIDATION_MATRIX.md"
CHECKLIST = REPO_ROOT / "docs" / "RELEASE_CHECKLIST.md"


def test_generated_artifact_validation_matrix_covers_required_artifacts():
    text = MATRIX.read_text(encoding="utf-8")

    required_artifacts = [
        "Architecture Package HTML",
        "Architecture Package target SVG",
        "Architecture Package DR SVG",
        "Classic diagram exports",
        "IaC output",
        "HLD markdown",
        "HLD DOCX/PDF/PPTX",
        "Cost estimate JSON",
        "Cost CSV",
        "OpenAPI schema",
    ]
    for artifact in required_artifacts:
        assert artifact in text

    required_columns = [
        "Owner Agent",
        "Contract Test",
        "Snapshot Test",
        "Production Smoke",
        "Fixture / Sample",
        "Release Evidence",
        "Gap Tracking",
    ]
    for column in required_columns:
        assert column in text


def test_release_checklist_links_generated_artifact_validation_matrix():
    checklist = CHECKLIST.read_text(encoding="utf-8")
    assert "GENERATED_ARTIFACT_VALIDATION_MATRIX.md" in checklist