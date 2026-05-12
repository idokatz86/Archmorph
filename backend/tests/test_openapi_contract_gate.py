import json
from pathlib import Path

from check_openapi_contract import detect_breaking_changes, validate_breaking_change_metadata


def test_detect_breaking_changes_flags_removed_operation():
    base = {
        "paths": {
            "/api/contact": {
                "get": {
                    "responses": {
                        "200": {"description": "OK"},
                    }
                }
            }
        },
        "components": {"schemas": {}},
    }
    target = {
        "paths": {},
        "components": {"schemas": {}},
    }

    breaking = detect_breaking_changes(base, target)
    assert any("Removed path: /api/contact" in item for item in breaking)


def test_breaking_change_metadata_is_required(tmp_path: Path):
    errors = validate_breaking_change_metadata(tmp_path / "missing.json")
    assert errors
    assert "Missing metadata file" in errors[0]


def test_breaking_change_metadata_accepts_required_fields(tmp_path: Path):
    metadata_path = tmp_path / "openapi.breaking-change.json"
    metadata_path.write_text(
        json.dumps(
            {
                "approved_by": "api-team",
                "review_url": "https://github.com/idokatz86/Archmorph/pull/999",
                "reason": "Intentional versioned removal with migration plan",
            }
        ),
        encoding="utf-8",
    )

    assert validate_breaking_change_metadata(metadata_path) == []
