import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
TEST_INVENTORY = ROOT / "docs/testing/ci-test-inventory.json"


def _terraform_resource_block(terraform: str, resource_type: str, name: str) -> str:
    marker = f'resource "{resource_type}" "{name}"'
    assert marker in terraform, f"Missing Terraform resource: {marker}"
    start = terraform.index(marker)
    next_resource = terraform.find('\nresource "', start + len(marker))
    if next_resource == -1:
        return terraform[start:]
    return terraform[start:next_resource]


def _tracked_test_directories() -> set[str]:
    tracked_files = _tracked_files()
    test_directories = set()
    for tracked_file in tracked_files:
        parts = Path(tracked_file).parts
        for index, part in enumerate(parts[:-1]):
            if part in {"test", "tests", "__tests__"}:
                test_directories.add(Path(*parts[: index + 1]).as_posix())
    return test_directories


def _tracked_files() -> set[str]:
    return set(
        subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )


def _workflow_job_block(workflow: str, job: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(job)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        workflow,
    )
    assert match is not None, f"Missing CI job: {job}"
    return match.group("body")


def test_root_pytest_suite_and_inventory_exclusions_are_collected_by_ci():
    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    repository_policy_job = _workflow_job_block(ci_workflow, "repository-policy")
    inventory = json.loads(TEST_INVENTORY.read_text(encoding="utf-8"))
    root_entry = next(
        entry for entry in inventory["test_directories"] if entry["directory"] == "tests"
    )
    exceptions = root_entry["test_file_exceptions"]
    exception_files = {entry["file"] for entry in exceptions}
    tracked_files = _tracked_files()
    root_pytest_candidates = {
        path
        for path in tracked_files
        if Path(path).is_relative_to(Path("tests"))
        and (
            Path(path).name.startswith("test_")
            or Path(path).name.endswith("_test.py")
        )
    }
    root_test_like_scripts = {
        path
        for path in tracked_files
        if Path(path).is_relative_to(Path("tests"))
        and Path(path).suffix == ".py"
        and (
            Path(path).name.startswith("test_")
            or Path(path).name.endswith("_test.py")
            or Path(path).name.startswith("locustfile")
        )
    }
    pytest_excluded_files = exception_files & root_pytest_candidates

    assert "Run root repository-policy tests" in repository_policy_job
    assert "python -m pytest -q tests \\" in repository_policy_job
    assert "Validate root Locust workload collection" in repository_policy_job
    assert "python -m locust -f tests/load_test.py --list" in repository_policy_job
    assert len(exception_files) == len(exceptions), "Duplicate root test-file exception"
    assert exception_files <= root_test_like_scripts
    assert all(entry["reason"].strip() for entry in exceptions)
    assert set(re.findall(r"--ignore=([^\s\\]+)", repository_policy_job)) == pytest_excluded_files
    pytest_collected_files = root_pytest_candidates - pytest_excluded_files
    assert root_test_like_scripts == pytest_collected_files | exception_files
    assert "tests/test_infra_policy_ci.py" in pytest_collected_files
    assert "tests/test_source_boundaries.py" not in exception_files

    vision_exception = next(
        entry for entry in exceptions if entry["file"] == "tests/test_vision_quick.py"
    )
    assert vision_exception["classification"] == "manual-local-path"
    assert "local developer image paths" in vision_exception["reason"]

    for entry in exceptions:
        if entry["classification"] == "manual-local-path":
            continue
        assert entry["classification"] == "separately-collected"
        workflow_path = ROOT / entry["workflow"]
        workflow = workflow_path.read_text(encoding="utf-8")
        job = _workflow_job_block(workflow, entry["job"])
        assert entry["command"] in job


def test_every_tracked_test_directory_has_a_named_ci_job():
    inventory = json.loads(TEST_INVENTORY.read_text(encoding="utf-8"))
    entries = inventory["test_directories"]
    inventoried_directories = {entry["directory"] for entry in entries}

    assert inventory["version"] == 1
    assert len(inventoried_directories) == len(entries), "Duplicate test directory in CI inventory"
    assert inventoried_directories == _tracked_test_directories()

    for entry in entries:
        workflow_path = ROOT / entry["workflow"]
        assert workflow_path.is_file(), f"Missing workflow for {entry['directory']}: {entry['workflow']}"
        workflow = workflow_path.read_text(encoding="utf-8")
        _workflow_job_block(workflow, entry["job"])


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


def test_runtime_probes_separate_liveness_from_schema_readiness():
    infra = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    variables = (ROOT / "infra/variables.tf").read_text(encoding="utf-8")

    readiness_variable = variables.split(
        'variable "readiness_probe_path"', 1
    )[1].split("}", 1)[0]
    liveness_variable = variables.split(
        'variable "liveness_probe_path"', 1
    )[1].split("}", 1)[0]
    assert 'default     = "/readyz"' in readiness_variable
    assert 'default     = "/healthz"' in liveness_variable

    liveness_block = infra.split("liveness_probe {", 1)[1].split("}", 1)[0]
    readiness_block = infra.split("readiness_probe {", 1)[1].split("}", 1)[0]
    startup_block = infra.split("startup_probe {", 1)[1].split("}", 1)[0]
    assert "path                    = var.liveness_probe_path" in liveness_block
    assert "path                    = var.readiness_probe_path" in readiness_block
    assert "path                    = var.liveness_probe_path" in startup_block


def test_external_health_routes_use_probe_safe_readiness():
    infra = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    dr = (ROOT / "infra/dr/main.tf").read_text(encoding="utf-8")
    helm_values = (ROOT / "charts/archmorph/values.yaml").read_text(encoding="utf-8")

    availability_block = _terraform_resource_block(
        infra,
        "azurerm_application_insights_standard_web_test",
        "health_check",
    )
    front_door_block = _terraform_resource_block(
        infra,
        "azurerm_cdn_frontdoor_origin_group",
        "api",
    )
    dr_readiness_variable = dr.split(
        'variable "readiness_probe_path"', 1
    )[1].split("}", 1)[0]
    traffic_manager_monitor = dr.split("monitor_config {", 1)[1].split("}", 1)[0]
    assert "${var.readiness_probe_path}" in availability_block
    assert "path                = var.readiness_probe_path" in front_door_block
    assert 'default     = "/readyz"' in dr_readiness_variable
    assert "path                         = var.readiness_probe_path" in traffic_manager_monitor
    assert "readinessProbe:\n  httpGet:\n    path: /readyz" in helm_values
    assert "livenessProbe:\n  httpGet:\n    path: /healthz" in helm_values
    assert "startupProbe:\n  httpGet:\n    path: /healthz" in helm_values


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
    assert check.scan_resource_conf({"network_rules": [{"default_action": "Deny", "bypass": []}]}) == CheckResult.FAILED
    assert check.scan_resource_conf({"network_rules": [{"default_action": ["Deny"], "bypass": ["Logging"]}]}) == CheckResult.FAILED


def test_storage_bypass_policy_passes_when_azure_services_in_bypass():
    """CKV_ARCHMORPH_5 must pass when AzureServices is in the bypass list."""
    import sys
    sys.path.insert(0, str(ROOT / "infra/policies/checkov"))
    from azure_storage_prod_network_bypass import AzureStorageProdNetworkBypass
    check = AzureStorageProdNetworkBypass()

    from checkov.common.models.enums import CheckResult
    assert check.scan_resource_conf({"network_rules": [{"default_action": "Deny", "bypass": ["AzureServices"]}]}) == CheckResult.PASSED
    assert check.scan_resource_conf({"network_rules": [{"default_action": ["Deny"], "bypass": ["Logging", "AzureServices"]}]}) == CheckResult.PASSED
    # Allow-by-default rules are not deny-without-path risks.
    assert check.scan_resource_conf({"network_rules": [{"default_action": "Allow", "bypass": []}]}) == CheckResult.PASSED
    # No network rules at all — no deny-without-path risk
    assert check.scan_resource_conf({}) == CheckResult.PASSED


def test_metrics_container_is_terraform_managed_in_primary_storage():
    infra = (ROOT / "infra/main.tf").read_text(encoding="utf-8")

    metrics_block = _terraform_resource_block(infra, "azurerm_storage_container", "metrics")
    assert 'name                  = "metrics"' in metrics_block
    assert "storage_account_id    = azurerm_storage_account.main.id" in metrics_block


def test_ci_does_not_create_persistent_metrics_storage_or_use_storage_connection_string():
    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Validate Terraform-managed metrics storage" in ci_workflow
    assert "az storage account create" not in ci_workflow
    assert "az storage container exists" not in ci_workflow
    assert "https://management.azure.com${METRICS_CONTAINER_ID}" in ci_workflow
    assert "AZURE_STORAGE_CONNECTION_STRING=secretref:storage-connection" not in ci_workflow
    assert "storage-connection=" not in ci_workflow
    assert 'select(.name == "AZURE_STORAGE_ACCOUNT_URL")' in ci_workflow


def test_ci_and_prod_workflows_enforce_readonly_terraform_lockfiles():
    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    prod_workflow = (ROOT / ".github/workflows/terraform-prod.yml").read_text(encoding="utf-8")
    combined_workflows = ci_workflow + "\n" + prod_workflow

    assert "terraform -chdir=\"$dir\" init -backend=false -input=false -lockfile=readonly" in ci_workflow
    assert "terraform -chdir=infra init -input=false -lockfile=readonly" in ci_workflow
    assert "terraform init -backend=false -input=false -lockfile=readonly" in prod_workflow
    assert "terraform init -input=false -lockfile=readonly" in prod_workflow
    non_readonly_inits = []
    for line in combined_workflows.splitlines():
        stripped = line.strip()
        command = re.sub(r"^(-\s*)?run:\s*", "", stripped).strip()
        if command.startswith(("echo ", "fail(")):
            continue
        if re.search(r"(?:^|[\s;&|()])terraform(?:\s+-chdir=(?:\"[^\"]+\"|\S+))?\s+init\b", command):
            if "-lockfile=readonly" not in command:
                non_readonly_inits.append(stripped)
    assert non_readonly_inits == []


def test_ci_validates_prod_storage_network_and_user_assigned_identity_role():
    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert '[ "$PUBLIC_NETWORK_ACCESS" = "Disabled" ]' in ci_workflow
    assert "APPROVED_PRIVATE_ENDPOINT_COUNT=$(az network private-endpoint-connection list" in ci_workflow
    assert "PRIVATE_ENDPOINT_STATUS=$?" in ci_workflow
    assert "ALLOW_PUBLIC_STORAGE_NETWORK_CUTOVER" not in ci_workflow
    assert "public-network cutover is forbidden" in ci_workflow
    assert "must have public network access Disabled" in ci_workflow
    assert "TERRAFORM_STORAGE_CANDIDATES=$(az storage account list" in ci_workflow
    assert "tags.project=='archmorph'" in ci_workflow
    assert "tags.managed_by=='terraform'" in ci_workflow
    assert "No tagged Terraform-managed Archmorph storage accounts were found" in ci_workflow
    assert '-o tsv | grep -vxF "$LEGACY_METRICS_STORAGE_ACCOUNT" || true' in ci_workflow
    assert "No Terraform-managed Archmorph storage account candidates were found" in ci_workflow
    assert "CANDIDATE_METRICS_CONTAINER_ID" in ci_workflow
    assert "NOT_FOUND_STORAGE_NAMES=()" in ci_workflow
    assert "StatusCode=404|ResourceNotFound|ContainerNotFound|NotFound" in ci_workflow
    assert "Unable to query a candidate metrics container through Azure Resource Manager" in ci_workflow
    assert "CREATE_METRICS_CONTAINER=true" in ci_workflow
    assert '[ "${#CANDIDATE_STORAGE_NAMES[@]}" -eq 1 ]' in ci_workflow
    assert '[ "${#NOT_FOUND_STORAGE_NAMES[@]}" -eq 1 ]' in ci_workflow
    assert "Metrics container was not found on the selected storage account" in ci_workflow
    assert "publicAccess\":\"None" in ci_workflow
    assert "Selected storage account must have shared-key access disabled" in ci_workflow
    assert "--public-network-access Enabled" not in ci_workflow
    assert "az storage account network-rule add" not in ci_workflow
    assert "Expected exactly one Terraform-managed Archmorph storage account with a metrics container" in ci_workflow
    assert 'select(.name == "AZURE_CLIENT_ID")' in ci_workflow
    assert "identity.userAssignedIdentities" in ci_workflow
    assert "Storage Blob Data Contributor" in ci_workflow
