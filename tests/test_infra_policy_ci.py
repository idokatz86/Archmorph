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
    assert "CKV_ARCHMORPH_1,CKV_ARCHMORPH_2,CKV_ARCHMORPH_3,CKV_ARCHMORPH_4,CKV_ARCHMORPH_5" in ci_workflow


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


# ──────────────────────────────────────────────────────────────────────────────
# Redis private connectivity guardrails
# ──────────────────────────────────────────────────────────────────────────────

def test_enable_redis_private_endpoint_defaults_to_true():
    """Changing the default to false would silently break prod Redis connectivity."""
    variables = (ROOT / "infra/variables.tf").read_text(encoding="utf-8")
    # Find the variable block
    assert 'variable "enable_redis_private_endpoint"' in variables
    block_start = variables.index('variable "enable_redis_private_endpoint"')
    block = variables[block_start:block_start + 300]
    assert "default     = true" in block


def test_redis_lifecycle_precondition_blocks_prod_without_private_endpoint():
    """Redis must have a lifecycle precondition that fails when prod has no private endpoint."""
    infra = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    redis_block = _terraform_resource_block(infra, "azurerm_redis_cache", "main")
    assert "lifecycle" in redis_block
    assert "precondition" in redis_block
    assert "enable_redis_private_endpoint" in redis_block
    assert "error_message" in redis_block


def test_redis_private_endpoint_resources_created_for_prod():
    """Redis private DNS zone, VNet link, and private endpoint must exist for prod."""
    infra = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    redis_pe_block = _terraform_resource_block(infra, "azurerm_private_endpoint", "redis")
    assert "archmorph-redis-pe" in redis_pe_block
    assert "azurerm_subnet.private_endpoints.id" in redis_pe_block
    assert '"redisCache"' in redis_pe_block
    assert "enable_redis_private_endpoint" in redis_pe_block

    redis_dns_block = _terraform_resource_block(infra, "azurerm_private_dns_zone", "redis")
    assert 'name                = "privatelink.redis.cache.windows.net"' in redis_dns_block


def test_redis_policy_fails_when_public_access_is_true():
    """CKV_ARCHMORPH_4 must fail for Redis with public_network_access_enabled=true."""
    import sys
    sys.path.insert(0, str(ROOT / "infra/policies/checkov"))
    from azure_redis_prod_private_connectivity import AzureRedisNoPublicAccess
    check = AzureRedisNoPublicAccess()

    from checkov.common.models.enums import CheckResult
    assert check.scan_resource_conf({"public_network_access_enabled": [True]}) == CheckResult.FAILED
    assert check.scan_resource_conf({"public_network_access_enabled": ["true"]}) == CheckResult.FAILED


def test_redis_policy_passes_when_public_access_is_false_or_absent():
    """CKV_ARCHMORPH_4 must pass for Redis with public access disabled or controlled via expression."""
    import sys
    sys.path.insert(0, str(ROOT / "infra/policies/checkov"))
    from azure_redis_prod_private_connectivity import AzureRedisNoPublicAccess
    check = AzureRedisNoPublicAccess()

    from checkov.common.models.enums import CheckResult
    assert check.scan_resource_conf({"public_network_access_enabled": [False]}) == CheckResult.PASSED
    assert check.scan_resource_conf({"public_network_access_enabled": ["false"]}) == CheckResult.PASSED
    # Ternary expression — not literally True, should pass
    assert check.scan_resource_conf({"public_network_access_enabled": ['${var.environment == "prod" ? false : true}']}) == CheckResult.PASSED
    # Absent — PASSED (not explicitly public)
    assert check.scan_resource_conf({}) == CheckResult.PASSED


# ──────────────────────────────────────────────────────────────────────────────
# Storage private connectivity guardrails
# ──────────────────────────────────────────────────────────────────────────────

def test_enable_storage_private_endpoint_variable_exists_and_defaults_to_true():
    """enable_storage_private_endpoint must exist and default to true."""
    variables = (ROOT / "infra/variables.tf").read_text(encoding="utf-8")
    assert 'variable "enable_storage_private_endpoint"' in variables
    block_start = variables.index('variable "enable_storage_private_endpoint"')
    block = variables[block_start:block_start + 300]
    assert "default     = true" in block


def test_storage_lifecycle_precondition_blocks_prod_without_private_endpoint():
    """Storage must have a lifecycle precondition that fails when prod has no private endpoint."""
    infra = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    storage_block = _terraform_resource_block(infra, "azurerm_storage_account", "main")
    assert "lifecycle" in storage_block
    assert "precondition" in storage_block
    assert "enable_storage_private_endpoint" in storage_block
    assert "error_message" in storage_block


def test_storage_network_rules_include_container_apps_subnet_in_prod():
    """Storage network_rules must reference container_apps subnet in prod."""
    infra = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    storage_block = _terraform_resource_block(infra, "azurerm_storage_account", "main")
    assert "network_rules" in storage_block
    assert "azurerm_subnet.container_apps.id" in storage_block


def test_storage_public_network_access_disabled_in_prod():
    """Storage public_network_access_enabled must use a conditional that disables it in prod."""
    infra = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    storage_block = _terraform_resource_block(infra, "azurerm_storage_account", "main")
    # The value must use a conditional that resolves to false in prod
    assert 'public_network_access_enabled' in storage_block
    # Should NOT be unconditionally true
    assert 'public_network_access_enabled     = true' not in storage_block


def test_storage_private_endpoint_resources_created_for_prod():
    """Storage private DNS zone, VNet link, and private endpoint must exist for prod."""
    infra = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    storage_pe_block = _terraform_resource_block(infra, "azurerm_private_endpoint", "storage")
    assert "archmorph-storage-pe" in storage_pe_block
    assert "azurerm_subnet.private_endpoints.id" in storage_pe_block
    assert '"blob"' in storage_pe_block
    assert "enable_storage_private_endpoint" in storage_pe_block

    storage_dns_block = _terraform_resource_block(infra, "azurerm_private_dns_zone", "storage")
    assert 'name                = "privatelink.blob.core.windows.net"' in storage_dns_block


def test_container_apps_subnet_has_storage_service_endpoint():
    """container_apps subnet must declare Microsoft.Storage service endpoint for prod VNet path."""
    infra = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    subnet_block = _terraform_resource_block(infra, "azurerm_subnet", "container_apps")
    assert "Microsoft.Storage" in subnet_block


def test_storage_bypass_policy_fails_when_azure_services_missing():
    """CKV_ARCHMORPH_5 must fail when AzureServices is absent from bypass list."""
    import sys
    sys.path.insert(0, str(ROOT / "infra/policies/checkov"))
    from azure_storage_prod_network_bypass import AzureStorageProdNetworkBypass
    check = AzureStorageProdNetworkBypass()

    from checkov.common.models.enums import CheckResult
    assert check.scan_resource_conf({"network_rules": [{"bypass": []}]}) == CheckResult.FAILED
    assert check.scan_resource_conf({"network_rules": [{"bypass": ["Logging"]}]}) == CheckResult.FAILED


def test_storage_bypass_policy_passes_when_azure_services_in_bypass():
    """CKV_ARCHMORPH_5 must pass when AzureServices is in the bypass list."""
    import sys
    sys.path.insert(0, str(ROOT / "infra/policies/checkov"))
    from azure_storage_prod_network_bypass import AzureStorageProdNetworkBypass
    check = AzureStorageProdNetworkBypass()

    from checkov.common.models.enums import CheckResult
    assert check.scan_resource_conf({"network_rules": [{"bypass": ["AzureServices"]}]}) == CheckResult.PASSED
    assert check.scan_resource_conf({"network_rules": [{"bypass": ["Logging", "AzureServices"]}]}) == CheckResult.PASSED
    # No network rules at all — no deny-without-path risk
    assert check.scan_resource_conf({}) == CheckResult.PASSED
