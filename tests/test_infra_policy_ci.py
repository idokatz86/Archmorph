from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _terraform_resource_block(terraform: str, resource_type: str, name: str) -> str:
    marker = f'resource "{resource_type}" "{name}"'
    assert marker in terraform, f"Missing Terraform resource: {marker}"
    start = terraform.index(marker)
    next_resource = terraform.find('\nresource "', start + len(marker))
    if next_resource == -1:
        return terraform[start:]
    return terraform[start:next_resource]


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


def test_required_tags_policy_does_not_pass_arbitrary_tag_expressions():
    policy = (ROOT / "infra/policies/checkov/azure_required_tags.py").read_text(encoding="utf-8")

    assert "APPROVED_TAG_REFERENCES" in policy
    assert "${local.tags}" in policy
    assert "var.tags" not in policy


def test_checked_in_postgres_explicitly_disables_public_network_access():
    infra = (ROOT / "infra/main.tf").read_text(encoding="utf-8")

    assert 'resource "azurerm_postgresql_flexible_server" "main"' in infra
    postgres_block = infra.split('resource "azurerm_postgresql_flexible_server" "main"', 1)[1].split('resource "azurerm_postgresql_flexible_server_database"', 1)[0]
    assert "public_network_access_enabled = false" in postgres_block


def test_container_apps_subnet_nsg_blocks_lateral_inbound_probe():
    infra = (ROOT / "infra/main.tf").read_text(encoding="utf-8")

    association_block = _terraform_resource_block(
        infra,
        "azurerm_subnet_network_security_group_association",
        "container_apps",
    )
    assert "subnet_id                 = azurerm_subnet.container_apps.id" in association_block
    assert "network_security_group_id = azurerm_network_security_group.container_apps.id" in association_block

    nsg_block = _terraform_resource_block(infra, "azurerm_network_security_group", "container_apps")
    assert 'name                       = "DenyAllInbound"' in nsg_block
    assert 'priority                   = 4000' in nsg_block
    assert 'direction                  = "Inbound"' in nsg_block
    assert 'access                     = "Deny"' in nsg_block
    assert 'source_address_prefix      = "*"' in nsg_block
    assert 'destination_address_prefix = "*"' in nsg_block
    assert 'destination_port_range     = "*"' in nsg_block
    assert 'source_address_prefix      = "VirtualNetwork"' not in nsg_block
    assert 'destination_port_range     = "8000"' not in nsg_block


def test_metrics_container_is_terraform_managed_in_primary_storage():
    infra = (ROOT / "infra/main.tf").read_text(encoding="utf-8")

    metrics_block = _terraform_resource_block(infra, "azurerm_storage_container", "metrics")
    assert 'name                  = "metrics"' in metrics_block
    assert "storage_account_id    = azurerm_storage_account.main.id" in metrics_block


def test_ci_does_not_create_persistent_metrics_storage_or_use_storage_connection_string():
    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Validate Terraform-managed metrics storage" in ci_workflow
    assert "az storage account create" not in ci_workflow
    assert "AZURE_STORAGE_CONNECTION_STRING=secretref:storage-connection" not in ci_workflow
    assert "storage-connection=" not in ci_workflow
    assert 'select(.name == "AZURE_STORAGE_ACCOUNT_URL")' in ci_workflow


def test_ci_and_prod_workflows_enforce_readonly_terraform_lockfiles():
    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    prod_workflow = (ROOT / ".github/workflows/terraform-prod.yml").read_text(encoding="utf-8")

    assert "terraform -chdir=\"$dir\" init -backend=false -input=false -lockfile=readonly" in ci_workflow
    assert "terraform init -backend=false -input=false -lockfile=readonly" in prod_workflow
    assert "terraform init -input=false -lockfile=readonly" in prod_workflow
