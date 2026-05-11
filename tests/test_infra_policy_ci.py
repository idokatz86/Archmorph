from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_runs_archmorph_checkov_policy_gate():
    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "terraform-policy-as-code" in ci_workflow
    assert "checkov" in ci_workflow
    assert "infra/policies/checkov" in ci_workflow
    assert "CKV_ARCHMORPH_1,CKV_ARCHMORPH_2,CKV_ARCHMORPH_3" in ci_workflow


def test_public_postgres_policy_fails_missing_or_enabled_public_access():
    policy = (ROOT / "infra/policies/checkov/azure_postgresql_no_public_access.py").read_text(encoding="utf-8")

    assert "CKV_ARCHMORPH_2" in policy
    assert 'supported_resources=("azurerm_postgresql_flexible_server",)' in policy
    assert "return CheckResult.FAILED" in policy
    assert "public_network_access_enabled" in policy


def test_checked_in_postgres_explicitly_disables_public_network_access():
    infra = (ROOT / "infra/main.tf").read_text(encoding="utf-8")

    assert 'resource "azurerm_postgresql_flexible_server" "main"' in infra
    postgres_block = infra.split('resource "azurerm_postgresql_flexible_server" "main"', 1)[1].split('resource "azurerm_postgresql_flexible_server_database"', 1)[0]
    assert "public_network_access_enabled = false" in postgres_block