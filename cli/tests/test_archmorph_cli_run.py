import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import archmorph_cli


class FakeArchmorphClient:
    def __init__(self, base_url, api_key=None, token=None):
        self.base_url = base_url
        self.api_key = api_key
        self.token = token
        self.generated = []
        self.pushed = None
        self.restored_analysis = None

    def upload_diagram(self, image_path, project_id="default"):
        assert Path(image_path).exists()
        assert project_id == "default"
        return {"diagram_id": "diag-test-660", "export_capability": "cap-upload"}

    def analyze_diagram(self, diagram_id):
        assert diagram_id == "diag-test-660"
        return {
            "diagram_id": diagram_id,
            "source_provider": "aws",
            "target_provider": "azure",
            "services_detected": 2,
            "export_capability": "cap-random-response-token",
            "export_capability_expires_in": 600,
            "mappings": [
                {"source_service": "EC2", "azure_service": "Azure Virtual Machines", "category": "Compute"},
                {"source_service": "S3", "azure_service": "Azure Blob Storage", "category": "Storage"},
            ],
        }

    def restore_session(self, diagram_id, analysis):
        assert diagram_id == "diag-test-660"
        self.restored_analysis = analysis
        return {"status": "restored", "diagram_id": diagram_id}

    def generate_iac_with_options(self, diagram_id, fmt="terraform", force=False):
        assert diagram_id == "diag-test-660"
        assert force is False
        self.generated.append(fmt)
        if fmt == "terraform":
            return {"code": 'resource "azurerm_resource_group" "main" {\n  name = "rg-demo"\n}\n'}
        if fmt == "bicep":
            return {"code": "targetScope = 'resourceGroup'\nresource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {\n  name: 'st660'\n}\n"}
        return {"code": "Resources:\n  Bucket:\n    Type: AWS::S3::Bucket\n"}

    def export_landing_zone_svg(self, diagram_id, dr_variant="primary"):
        assert diagram_id == "diag-test-660"
        assert dr_variant == "primary"
        return {"content": '<svg xmlns="http://www.w3.org/2000/svg"><title>Target</title></svg>', "export_capability": "cap-next"}

    def cost_estimate(self, diagram_id):
        assert diagram_id == "diag-test-660"
        return {
            "diagram_id": diagram_id,
            "currency": "USD",
            "total_monthly_estimate": {"low": 10, "high": 20},
            "services": [{"service": "Azure Blob Storage", "monthly_low": 10, "monthly_high": 20}],
        }

    def push_iac_pr(
        self,
        repo,
        iac_code,
        iac_format,
        base_branch="main",
        target_path=None,
        analysis_summary=None,
        cost_estimate=None,
    ):
        self.pushed = {
            "repo": repo,
            "iac_code": iac_code,
            "iac_format": iac_format,
            "base_branch": base_branch,
            "target_path": target_path,
            "analysis_summary": analysis_summary,
            "cost_estimate": cost_estimate,
        }
        return {"success": True, "pr_url": "https://github.com/acme/infra/pull/1"}


def test_run_emits_full_spine_artifacts(monkeypatch, tmp_path):
    client = FakeArchmorphClient("http://api.test")

    class ClientFactory(FakeArchmorphClient):
        def __new__(cls, *args, **kwargs):
            return client

    monkeypatch.setattr(archmorph_cli, "ArchmorphClient", ClientFactory)
    diagram = tmp_path / "aws.png"
    diagram.write_bytes(b"\x89PNG\r\n\x1a\n")
    out_dir = tmp_path / "infra"

    result = CliRunner().invoke(
        archmorph_cli.cli,
        [
            "--api-url",
            "http://api.test",
            "run",
            "--diagram",
            str(diagram),
            "--target-rg",
            "rg-demo",
            "--emit",
            "terraform,bicep,alz-svg,cost",
            "--out",
            str(out_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    analysis = json.loads((out_dir / "analysis.json").read_text())
    assert analysis["diagram_id"] == "diag-test-660"
    assert analysis["iac_parameters"]["target_resource_group"] == "rg-demo"
    assert analysis["iac_parameters"]["project_name"] == "demo"
    assert "export_capability" not in analysis
    assert "export_capability_expires_in" not in analysis
    assert client.restored_analysis["cli_run"]["target_resource_group"] == "rg-demo"
    assert "export_capability" not in client.restored_analysis
    assert 'resource "azurerm_resource_group"' in (out_dir / "terraform" / "main.tf").read_text()
    assert "targetScope" in (out_dir / "bicep" / "main.bicep").read_text()
    ET.fromstring((out_dir / "alz.svg").read_text())
    cost = json.loads((out_dir / "cost-estimate.json").read_text())
    assert cost["currency"] == "USD"
    summary = json.loads((out_dir / "run-summary.json").read_text())
    assert summary["target_resource_group"] == "rg-demo"
    assert set(summary["emit"]) == {"terraform", "bicep", "alz-svg", "cost"}


def test_run_push_pr_uses_first_generated_iac(monkeypatch, tmp_path):
    client = FakeArchmorphClient("http://api.test")

    class ClientFactory(FakeArchmorphClient):
        def __new__(cls, *args, **kwargs):
            return client

    monkeypatch.setattr(archmorph_cli, "ArchmorphClient", ClientFactory)
    diagram = tmp_path / "aws.png"
    diagram.write_bytes(b"\x89PNG\r\n\x1a\n")

    result = CliRunner().invoke(
        archmorph_cli.cli,
        [
            "run",
            "--diagram",
            str(diagram),
            "--emit",
            "bicep,cost",
            "--out",
            str(tmp_path / "out"),
            "--push-pr",
            "acme/infra",
            "--pr-base",
            "develop",
            "--pr-path",
            "deploy/main.bicep",
        ],
    )

    assert result.exit_code == 0, result.output
    assert client.pushed["repo"] == "acme/infra"
    assert client.pushed["iac_format"] == "bicep"
    assert client.pushed["base_branch"] == "develop"
    assert client.pushed["target_path"] == "deploy/main.bicep"
    assert client.pushed["analysis_summary"]["diagram_id"] == "diag-test-660"
    pr = json.loads((tmp_path / "out" / "github-pr.json").read_text())
    assert pr["success"] is True
    assert "GitHub PR created: https://github.com/acme/infra/pull/1" in result.output


def test_run_rejects_unknown_emit_target(tmp_path):
    diagram = tmp_path / "aws.png"
    diagram.write_bytes(b"\x89PNG\r\n\x1a\n")

    result = CliRunner().invoke(
        archmorph_cli.cli,
        ["run", "--diagram", str(diagram), "--emit", "terraform,unknown", "--out", str(tmp_path / "out")],
    )

    assert result.exit_code != 0
    assert "Unsupported emit target" in result.output


def test_client_normalizes_api_suffix():
    client = archmorph_cli.ArchmorphClient("https://api.archmorphai.com/api")
    assert client._url("/api/health") == "https://api.archmorphai.com/api/health"
