from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
INFRA_MAIN = REPO_ROOT / "infra" / "main.tf"
INFRA_OUTPUTS = REPO_ROOT / "infra" / "outputs.tf"


def test_front_door_origin_uses_owned_endpoint_host_header():
    terraform = INFRA_MAIN.read_text(encoding="utf-8")

    assert 'origin_host_header             = azurerm_cdn_frontdoor_endpoint.api[0].host_name' in terraform


def test_container_app_receives_front_door_origin_lock_contract():
    terraform = INFRA_MAIN.read_text(encoding="utf-8")

    assert 'name  = "TRUSTED_FRONT_DOOR_FDID"' in terraform
    assert 'value = var.enable_front_door_waf ? azurerm_cdn_frontdoor_profile.main[0].resource_guid : ""' in terraform
    assert 'name  = "TRUSTED_FRONT_DOOR_HOSTS"' in terraform
    assert 'value = var.enable_front_door_waf ? azurerm_cdn_frontdoor_endpoint.api[0].host_name : ""' in terraform


def test_front_door_origin_lock_outputs_are_documented_in_terraform():
    outputs = INFRA_OUTPUTS.read_text(encoding="utf-8")

    assert 'output "front_door_api_hostname"' in outputs
    assert 'output "front_door_profile_resource_guid"' in outputs
