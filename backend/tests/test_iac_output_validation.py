"""CI gate for generated Terraform and Bicep artifacts (#653)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from routers.shared import SESSION_STORE


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "iac_canonical"


def _fixture_paths() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*.json"))


def _terraform_code(name: str) -> str:
    return f"""terraform {{
  required_version = ">= 1.5"
  required_providers {{
    azurerm = {{
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }}
  }}
}}

provider "azurerm" {{
  features {{}}
}}

resource "azurerm_resource_group" "main" {{
  name     = "rg-{name}-dev"
  location = "westeurope"
  tags = {{
    workload    = "{name}"
    environment = "dev"
    managed_by  = "archmorph"
  }}
}}
"""


def _bicep_code(name: str) -> str:
    return f"""targetScope = 'subscription'

param location string = 'westeurope'

resource rg 'Microsoft.Resources/resourceGroups@2023-07-01' = {{
  name: 'rg-{name}-dev'
  location: location
  tags: {{
    workload: '{name}'
    environment: 'dev'
    managedBy: 'archmorph'
  }}
}}
"""


def _generated_code(*, analysis: dict, iac_format: str) -> str:
    safe_name = Path(str(analysis.get("title", "iac"))).stem.lower().replace(" ", "-")[:24]
    return _terraform_code(safe_name) if iac_format == "terraform" else _bicep_code(safe_name)


def _completion_with_generated_iac(*, analysis: dict):
    def _mock_completion(messages, **kwargs):
        prompt = str(messages[-1]["content"]).lower()
        iac_format = "bicep" if "bicep" in prompt else "terraform"
        content = _generated_code(analysis=analysis, iac_format=iac_format)
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


def test_iac_fixture_matrix_contains_ten_representative_analyses():
    paths = _fixture_paths()
    assert len(paths) == 10
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