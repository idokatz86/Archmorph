"""CI gate for generated Terraform and Bicep artifacts (#653)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from routers.shared import SESSION_STORE


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "iac_canonical"
CONFORMANCE_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "iac_conformance"


def _fixture_paths() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*.json"))


def _conformance_fixture_paths(kind: str) -> list[Path]:
    return sorted((CONFORMANCE_FIXTURE_DIR / kind).glob("*.json"))


def _mapping_services(analysis: dict) -> list[str]:
    return [str(mapping["azure_service"]) for mapping in analysis.get("mappings", [])]


def _hcl_string(value: str) -> str:
    return value.replace('"', '\\"')


def _bicep_string(value: str) -> str:
    return value.replace("'", "''")


def _terraform_code(name: str, services: list[str]) -> str:
    service_values = "\n".join(f'    "{_hcl_string(service)}",' for service in services)
    return f"""terraform {{
  required_version = ">= 1.5"
}}

locals {{
  mapped_services = [
{service_values}
  ]
}}

resource "terraform_data" "main" {{
  input = {{
    name        = "rg-{name}-dev"
    location    = "westeurope"
    workload    = "{name}"
    environment = "dev"
    managed_by  = "archmorph"
  }}
}}

output "mapped_services" {{
  value = local.mapped_services
}}
"""


def _bicep_code(name: str, services: list[str]) -> str:
    service_values = "\n".join(f"  '{_bicep_string(service)}'" for service in services)
    return f"""targetScope = 'subscription'

param location string = 'westeurope'

var mappedServices = [
{service_values}
]

resource rg 'Microsoft.Resources/resourceGroups@2023-07-01' = {{
  name: 'rg-{name}-dev'
  location: location
  tags: {{
    workload: '{name}'
    environment: 'dev'
    managedBy: 'archmorph'
  }}
}}

output mappedServices array = mappedServices
"""


def _generated_code(*, analysis: dict, iac_format: str) -> str:
    safe_name = Path(str(analysis.get("title", "iac"))).stem.lower().replace(" ", "-")[:24]
    services = _mapping_services(analysis)
    return _terraform_code(safe_name, services) if iac_format == "terraform" else _bicep_code(safe_name, services)


def _completion_with_generated_iac(*, analysis: dict):
    expected_terms = [
        str(mapping.get(key, ""))
        for mapping in analysis.get("mappings", [])
        for key in ("source_service", "azure_service")
    ]

    def _mock_completion(messages, **kwargs):
        prompt = str(messages[-1]["content"])
        prompt_lower = prompt.lower()
        for term in expected_terms:
            assert term.lower() in prompt_lower, f"generator prompt omitted fixture mapping term: {term}"
        iac_format = "bicep" if "bicep" in prompt_lower else "terraform"
        content = _generated_code(analysis=analysis, iac_format=iac_format)
        response = MagicMock(choices=[MagicMock(message=MagicMock(content=content))])
        response._truncated = False
        return response

    return _mock_completion


def _completion_with_fixture_iac(*, terraform_code: str, bicep_code: str):
    def _mock_completion(messages, **kwargs):
        prompt = str(messages[-1]["content"]).lower()
        content = bicep_code if "bicep" in prompt else terraform_code
        response = MagicMock(choices=[MagicMock(message=MagicMock(content=content))])
        response._truncated = False
        return response

    return _mock_completion


def _require_toolchain() -> None:
    if os.getenv("ARCHMORPH_RUN_IAC_VALIDATE_TOOLS") != "1":
        pytest.skip("set ARCHMORPH_RUN_IAC_VALIDATE_TOOLS=1 to run Terraform/Bicep validation")
    missing = [tool for tool in ("terraform", "az") if shutil.which(tool) is None]
    if missing:
        pytest.fail(f"Missing required IaC validation tool(s): {', '.join(missing)}")


def _run(command: list[str], cwd: Path) -> None:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=90, check=False)
    assert result.returncode == 0, result.stderr or result.stdout


def _control_patterns(iac_format: str) -> dict[str, str]:
    if iac_format == "terraform":
        return {
            "managed_identity": r'(identity\s*\{[^}]*type\s*=\s*"(?:SystemAssigned|UserAssigned|SystemAssigned,\s*UserAssigned)")|(azurerm_user_assigned_identity)',
            "tls": r'(?:min_tls_version|minimum_tls_version)\s*=\s*"TLS1_2"',
            "diagnostics": r"azurerm_monitor_diagnostic_setting|Microsoft\.Insights/diagnosticSettings",
            "private_connectivity": r"azurerm_private_endpoint|public_network_access_enabled\s*=\s*false",
            "key_vault_handling": r"azurerm_key_vault|Microsoft\.KeyVault/vaults|key_vault_id",
            "waf_public_ingress_posture": r"web_application_firewall|waf_configuration|firewall_mode\s*=\s*\"Prevention\"",
            "required_tags": r"(project|environment|managed_by)\s*=\s*\"",
            "no_hardcoded_secrets": r"(?:password|secret|api_key|access_key|administrator_password)\s*=\s*['\"][^'\"]+['\"]",
        }
    return {
        "managed_identity": r"identity:\s*\{[^}]*type:\s*'(?:SystemAssigned|UserAssigned|SystemAssigned,\s*UserAssigned)'|Microsoft\.ManagedIdentity/userAssignedIdentities",
        "tls": r"(?:minTlsVersion|minimumTlsVersion)\s*:\s*'(?:1\.2|TLS1_2)'",
        "diagnostics": r"Microsoft\.Insights/diagnosticSettings",
        "private_connectivity": r"Microsoft\.Network/privateEndpoints|publicNetworkAccess:\s*'Disabled'",
        "key_vault_handling": r"Microsoft\.KeyVault/vaults|keyVault",
        "waf_public_ingress_posture": r"Microsoft\.Network/applicationGatewayWebApplicationFirewallPolicies|mode:\s*'Prevention'",
        "required_tags": r"(project|environment|managedBy)\s*:\s*'",
        "no_hardcoded_secrets": r"(?:password|secret|apiKey|accessKey|administratorLoginPassword)\s*:\s*['\"][^'\"]+['\"]",
    }


def _assert_conformance(*, code: str, iac_format: str, controls: list[str]) -> list[str]:
    patterns = _control_patterns(iac_format)
    missing: list[str] = []
    for control in controls:
        if control == "no_hardcoded_secrets":
            # This control is intentionally inverse: any match is a violation.
            if re.search(patterns[control], code, re.IGNORECASE):
                missing.append(control)
            continue
        if not re.search(patterns[control], code, re.IGNORECASE | re.DOTALL):
            missing.append(control)
    return missing


def test_iac_fixture_matrix_contains_ten_representative_analyses():
    paths = _fixture_paths()
    assert len(paths) >= 10
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload.get("mappings"), f"{path.name} must include mappings"


@pytest.mark.parametrize("fixture_path", _fixture_paths(), ids=lambda path: path.stem)
def test_generated_iac_artifacts_validate_via_cli(fixture_path: Path, tmp_path: Path):
    _require_toolchain()
    analysis = json.loads(fixture_path.read_text(encoding="utf-8"))
    diagram_id = f"iac-validate-{fixture_path.stem}"
    SESSION_STORE.set(diagram_id, analysis)

    try:
        with TestClient(app) as client, patch(
            "iac_generator.cached_chat_completion",
            side_effect=_completion_with_generated_iac(analysis=analysis),
        ):
            terraform_resp = client.post(f"/api/diagrams/{diagram_id}/generate?format=terraform&force=true")
            bicep_resp = client.post(f"/api/diagrams/{diagram_id}/generate?format=bicep&force=true")

        assert terraform_resp.status_code == 200, terraform_resp.text
        assert bicep_resp.status_code == 200, bicep_resp.text
        assert "failed terraform" not in terraform_resp.json()["code"]
        assert "failed az bicep build" not in bicep_resp.json()["code"]
        for service in _mapping_services(analysis):
            assert service in terraform_resp.json()["code"]
            assert service in bicep_resp.json()["code"]

        tf_dir = tmp_path / "terraform"
        tf_dir.mkdir()
        (tf_dir / "main.tf").write_text(terraform_resp.json()["code"], encoding="utf-8")
        _run(["terraform", "fmt", "-check", "-no-color", "main.tf"], tf_dir)
        _run(["terraform", "init", "-backend=false", "-input=false", "-no-color"], tf_dir)
        _run(["terraform", "validate", "-json", "-no-color"], tf_dir)

        bicep_dir = tmp_path / "bicep"
        bicep_dir.mkdir()
        bicep_file = bicep_dir / "main.bicep"
        bicep_file.write_text(bicep_resp.json()["code"], encoding="utf-8")
        _run(["az", "bicep", "build", "--file", str(bicep_file)], bicep_dir)
    finally:
        try:
            SESSION_STORE.delete(diagram_id)
        except Exception:
            pass


@pytest.mark.parametrize("fixture_path", _conformance_fixture_paths("golden"), ids=lambda path: path.stem)
def test_generated_iac_matches_golden_secure_fixtures(fixture_path: Path, monkeypatch):
    monkeypatch.setenv("ARCHMORPH_DISABLE_IAC_CLI_VALIDATION", "1")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    analysis = fixture["analysis"]
    diagram_id = f"iac-golden-{fixture_path.stem}"
    SESSION_STORE.set(diagram_id, analysis)

    try:
        with TestClient(app) as client, patch(
            "iac_generator.cached_chat_completion",
            side_effect=_completion_with_fixture_iac(
                terraform_code=fixture["terraform"],
                bicep_code=fixture["bicep"],
            ),
        ):
            terraform_resp = client.post(f"/api/diagrams/{diagram_id}/generate?format=terraform&force=true")
            bicep_resp = client.post(f"/api/diagrams/{diagram_id}/generate?format=bicep&force=true")

        assert terraform_resp.status_code == 200, terraform_resp.text
        assert bicep_resp.status_code == 200, bicep_resp.text
        assert fixture["terraform"].rstrip() in terraform_resp.json()["code"].rstrip()
        assert fixture["bicep"].rstrip() in bicep_resp.json()["code"].rstrip()

        controls = fixture["required_controls"]
        assert _assert_conformance(code=fixture["terraform"], iac_format="terraform", controls=controls) == []
        assert _assert_conformance(code=fixture["bicep"], iac_format="bicep", controls=controls) == []
    finally:
        try:
            SESSION_STORE.delete(diagram_id)
        except Exception:
            pass


@pytest.mark.parametrize("fixture_path", _conformance_fixture_paths("negative"), ids=lambda path: path.stem)
def test_negative_control_iac_fixtures_fail_conformance(fixture_path: Path):
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    expected = set(fixture["expected_violations"])
    tf_violations = set(_assert_conformance(code=fixture["terraform"], iac_format="terraform", controls=fixture["required_controls"]))
    bicep_violations = set(_assert_conformance(code=fixture["bicep"], iac_format="bicep", controls=fixture["required_controls"]))

    assert tf_violations, "negative Terraform fixture must violate at least one required control"
    assert bicep_violations, "negative Bicep fixture must violate at least one required control"
    assert expected.issubset(tf_violations)
    assert expected.issubset(bicep_violations)
