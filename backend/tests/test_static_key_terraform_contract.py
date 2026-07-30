"""Terraform contracts for static-key overlap/cutover wiring."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_terraform_wires_static_key_rotation_without_values():
    variables = (ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    main = (ROOT / "infra" / "main.tf").read_text(encoding="utf-8")

    assert 'variable "archmorph_api_key"' in variables
    assert 'variable "archmorph_api_key_rotated"' in variables
    assert 'variable "manage_archmorph_api_key"' in variables
    assert 'variable "manage_archmorph_api_key_rotated"' in variables
    assert 'variable "archmorph_api_key_principal_id"' in variables
    assert 'variable "archmorph_api_key_allow_legacy_overlap"' in variables
    assert 'name         = "archmorph-api-key"' in main
    assert 'name         = "archmorph-api-key-rotated"' in main
    assert 'name  = "ARCHMORPH_API_KEY_PRINCIPAL_ID"' in main
    assert 'name  = "ARCHMORPH_API_KEY_ALLOW_LEGACY_OVERLAP"' in main
    assert "your-base-api-key" not in main
    assert "your-current-api-key" not in main