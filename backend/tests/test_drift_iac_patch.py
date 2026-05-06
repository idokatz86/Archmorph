from drift_iac_patch import build_drift_iac_patch


def _finding(**overrides):
    finding = {
        "finding_id": "drift-api",
        "id": "api-prod",
        "status": "yellow",
        "message": "Configuration differs from baseline",
        "designed_data": {"id": "api-prod", "type": "container_app", "sku": "consumption"},
        "live_data": {"resource_id": "api-prod", "resource_type": "container_app", "sku": "dedicated"},
        "recommendation": "Review tracked settings.",
    }
    finding.update(overrides)
    return finding


def test_builds_deterministic_terraform_replacement_patch():
    current_iac = '''resource "azurerm_container_app" "api" {
  name = "api-prod"
  sku  = "consumption"
}
'''

    first = build_drift_iac_patch([_finding()], current_iac=current_iac, iac_format="terraform")
    second = build_drift_iac_patch([_finding()], current_iac=current_iac, iac_format="terraform")

    assert first == second
    assert first["review_only"] is True
    assert first["validates"] is True
    assert '-  sku  = "consumption"' in first["patch"]
    assert '+  sku  = "dedicated"' in first["patch"]
    assert first["applied_changes"] == ["sku"]


def test_no_drift_returns_empty_valid_patch():
    result = build_drift_iac_patch([
        _finding(status="green", message="Matched", designed_data={}, live_data={})
    ])

    assert result["patch"] == ""
    assert result["validates"] is True
    assert result["summary"] == "No drift findings require IaC changes."


def test_unsupported_shadow_resource_emits_review_artifact():
    result = build_drift_iac_patch([
        _finding(
            status="red",
            message="Shadow IT",
            designed_data=None,
            live_data={"resource_id": "redis-prod", "resource_type": "redis", "sku": "basic"},
            recommendation="Investigate ownership.",
        )
    ], iac_format="bicep")

    assert "archmorph-drift-remediation.bicep" in result["patch"]
    assert "redis-prod" in result["patch"]
    assert result["review_only"] is True


def test_secret_like_values_are_redacted_and_marked_not_validated():
    result = build_drift_iac_patch([
        _finding(
            designed_data={"id": "db", "type": "postgres", "secret_token": "old-token"},
            live_data={"resource_id": "db", "resource_type": "postgres", "secret_token": "new-token"},
        )
    ])

    assert "old-token" not in result["patch"]
    assert "new-token" not in result["patch"]
    assert "[REDACTED]" in result["patch"]
    assert result["validates"] is False
    assert result["warnings"] == ["Redacted secret-like value for secret_token."]