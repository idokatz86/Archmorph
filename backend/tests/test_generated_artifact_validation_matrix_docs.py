"""Release documentation guardrails for generated artifact validation (#669)."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX = REPO_ROOT / "docs" / "GENERATED_ARTIFACT_VALIDATION_MATRIX.md"
CHECKLIST = REPO_ROOT / "docs" / "RELEASE_CHECKLIST.md"
REQUIRED_COLUMNS = [
    "Artifact",
    "Owner Agent",
    "Contract Test",
    "Snapshot Test",
    "Production Smoke",
    "Fixture / Sample",
    "Release Evidence",
    "Gap Tracking",
]
REQUIRED_ARTIFACTS = [
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


def _matrix_rows():
    rows = []
    for line in MATRIX.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells[0] == "Artifact" or set(cells[0]) == {"-"}:
            continue
        rows.append(dict(zip(REQUIRED_COLUMNS, cells, strict=True)))
    return rows


def test_generated_artifact_validation_matrix_covers_required_artifacts():
    rows_by_artifact = {row["Artifact"]: row for row in _matrix_rows()}

    for artifact in REQUIRED_ARTIFACTS:
        assert artifact in rows_by_artifact

    for artifact, row in rows_by_artifact.items():
        for column in REQUIRED_COLUMNS:
            assert row[column], f"{artifact} is missing {column}"
        assert row["Owner Agent"].endswith("Master")
        assert row["Contract Test"].startswith("`") or "No dedicated" in row["Contract Test"]
        assert row["Fixture / Sample"] != "TBD"
        assert row["Release Evidence"] != "TBD"
        assert "#" in row["Gap Tracking"], f"{artifact} is missing issue tracking"


def test_release_checklist_links_generated_artifact_validation_matrix():
    checklist = CHECKLIST.read_text(encoding="utf-8")
    assert "GENERATED_ARTIFACT_VALIDATION_MATRIX.md" in checklist