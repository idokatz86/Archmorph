from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_azure_skills_upstream.py"
SPEC = spec_from_file_location("check_azure_skills_upstream", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
check_azure_skills_upstream = module_from_spec(SPEC)
sys.modules[SPEC.name] = check_azure_skills_upstream
SPEC.loader.exec_module(check_azure_skills_upstream)


def _lock():
    return {
        "upstream": {
            "pinned_sha": "27c9afeabd7912543d9a9041b9210b69adfd13f9",
            "expected_skill_count": 2,
            "expected_skill_names": ["azure-compute", "azure-storage"],
        },
        "custom_skills": [
            {
                "legacy_name": "azure-postgres",
                "protected_name": "archmorph-postgres",
            }
        ],
        "telemetry": {
            "env": "AZURE_MCP_COLLECT_TELEMETRY",
            "default": "false",
        },
    }


def _codes(findings):
    return {finding.code for finding in findings}


def test_governance_passes_when_pin_skill_names_and_customs_match():
    findings = check_azure_skills_upstream.evaluate_config(
        _lock(),
        upstream_skill_names={"azure-compute", "azure-storage"},
        local_skill_names={"archmorph-postgres"},
        submodule_sha="27c9afeabd7912543d9a9041b9210b69adfd13f9",
        telemetry_env="false",
        check_telemetry_env=True,
    )

    assert findings == []


def test_detects_submodule_sha_drift():
    findings = check_azure_skills_upstream.evaluate_config(
        _lock(),
        upstream_skill_names={"azure-compute", "azure-storage"},
        local_skill_names={"archmorph-postgres"},
        submodule_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )

    assert "submodule-drift" in _codes(findings)


def test_detects_upstream_skill_list_drift():
    findings = check_azure_skills_upstream.evaluate_config(
        _lock(),
        upstream_skill_names={"azure-compute", "azure-networking"},
        local_skill_names={"archmorph-postgres"},
        submodule_sha="27c9afeabd7912543d9a9041b9210b69adfd13f9",
    )

    assert "upstream-skill-drift" in _codes(findings)


def test_detects_legacy_local_skill_name():
    findings = check_azure_skills_upstream.evaluate_config(
        _lock(),
        upstream_skill_names={"azure-compute", "azure-storage"},
        local_skill_names={"azure-postgres"},
        submodule_sha="27c9afeabd7912543d9a9041b9210b69adfd13f9",
    )

    assert "legacy-local-skill" in _codes(findings)


def test_detects_protected_name_collision_with_upstream():
    findings = check_azure_skills_upstream.evaluate_config(
        _lock(),
        upstream_skill_names={"azure-compute", "azure-storage", "archmorph-postgres"},
        local_skill_names={"archmorph-postgres"},
        submodule_sha="27c9afeabd7912543d9a9041b9210b69adfd13f9",
    )

    assert "protected-name-collision" in _codes(findings)


def test_detects_telemetry_default_when_requested():
    findings = check_azure_skills_upstream.evaluate_config(
        _lock(),
        upstream_skill_names={"azure-compute", "azure-storage"},
        local_skill_names={"archmorph-postgres"},
        submodule_sha="27c9afeabd7912543d9a9041b9210b69adfd13f9",
        telemetry_env=None,
        check_telemetry_env=True,
    )

    assert "telemetry-default" in _codes(findings)


def test_local_upstream_diff_detects_content_drift(tmp_path):
    upstream = tmp_path / "upstream" / "azure-compute"
    local = tmp_path / "local" / "azure-compute"
    upstream.mkdir(parents=True)
    local.mkdir(parents=True)
    (upstream / "SKILL.md").write_text("pinned\n", encoding="utf-8")
    (local / "SKILL.md").write_text("local drift\n", encoding="utf-8")

    findings = check_azure_skills_upstream.diff_local_upstream(
        tmp_path / "upstream",
        tmp_path / "local",
        expected_skill_names={"azure-compute"},
    )

    assert "local-upstream-content-drift" in _codes(findings)


def test_local_upstream_diff_passes_for_identical_skill(tmp_path):
    upstream = tmp_path / "upstream" / "azure-compute"
    local = tmp_path / "local" / "azure-compute"
    upstream.mkdir(parents=True)
    local.mkdir(parents=True)
    (upstream / "SKILL.md").write_text("same\n", encoding="utf-8")
    (local / "SKILL.md").write_text("same\n", encoding="utf-8")

    findings = check_azure_skills_upstream.diff_local_upstream(
        tmp_path / "upstream",
        tmp_path / "local",
        expected_skill_names={"azure-compute"},
    )

    assert findings == []