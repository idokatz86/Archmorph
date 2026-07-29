"""Executable Helm release owner workflow contracts."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "helm-release.yml"
SCRIPT = ROOT / "scripts" / "helm_release.sh"


def test_helm_release_owner_serializes_and_records_evidence():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert "concurrency" not in workflow
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"environment", "build_run_id", "build_run_attempt"}
    assert workflow["permissions"]["actions"] == "read"
    assert workflow["permissions"]["attestations"] == "read"
    release = workflow["jobs"]["release"]
    names = [step.get("name") for step in release["steps"]]
    assert names.index("Azure Login (OIDC)") < names.index(
        "Resolve and verify immutable CI build evidence"
    )
    assert names.index("Resolve and verify immutable CI build evidence") < names.index(
        "Acquire cluster credentials"
    )
    assert names.index("Acquire cluster credentials") < names.index(
        "Acquire durable production rollout ownership"
    )
    assert names.index("Acquire durable production rollout ownership") < names.index(
        "Run serialized schema-bound Helm release"
    )
    assert names.index("Run serialized schema-bound Helm release") < names.index(
        "Validate Helm release evidence bundle"
    )
    assert names.index("Validate Helm release evidence bundle") < names.index(
        "Upload Helm release evidence"
    )
    validate = next(
        step for step in release["steps"] if step.get("name") == "Validate Helm release evidence bundle"
    )
    assert validate["if"] == "always()"
    upload = next(
        step for step in release["steps"] if step.get("name") == "Upload Helm release evidence"
    )
    assert "github.run_id" in upload["with"]["name"]
    assert "github.run_attempt" in upload["with"]["name"]
    evidence = next(
        step
        for step in release["steps"]
        if step.get("name") == "Resolve and verify immutable CI build evidence"
    )["run"]
    assert '.name == "CI/CD"' in evidence
    assert '.conclusion == "success"' in evidence
    assert "backend-build-evidence-${BUILD_RUN_ID}-${BUILD_RUN_ATTEMPT}" in evidence
    assert "verify-build-provenance" in evidence
    assert "gh attestation verify" in evidence
    assert "--deny-self-hosted-runners" in evidence
    assert "verify-image" in evidence
    assert "/app/release/schema-contract.json" in evidence
    assert "inputs.image_digest" not in WORKFLOW.read_text(encoding="utf-8")
    assert "HELM_SOURCE_SHA: ${{ github.sha }}" not in WORKFLOW.read_text(encoding="utf-8")


def test_helm_release_script_is_two_phase_secret_aware_and_digest_pinned():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "kubernetes_lease.py" in script
    assert "heartbeat" in script
    assert "--parent-pid $$" in script
    assert "--duration-seconds" in script
    assert "release >/dev/null" in script
    assert "kubectl api-resources --api-group=external-secrets.io" in script
    assert "External Secrets controller CRD is unavailable" in script
    assert "wait" in script and "condition=Ready=True" in script
    assert "get secret" in script
    assert "DATABASE_URL REDIS_URL" in script
    assert "--set externalSecrets.enabled=false" in script
    assert "upgrade --install" in script
    assert "--atomic --wait" not in script
    assert "--wait --timeout" in script
    assert "migrations.enabled=false" in script
    assert "migrations.phase=${phase}" in script
    assert "migration-secret-preflight.yaml" in script
    assert "migration-job.yaml" in script
    assert 'get serviceaccount "$job_service_account"' in script
    assert "release phase Job has no explicit ServiceAccount" in script
    assert "retain_bridge_and_fix_forward" not in script
    assert "post_migration_failure_action" in script
    assert "schema_committed" in script
    assert "migration_attempted" in script
    assert "retain_bridge_migration_outcome_requires_recovery" in script
    assert script.index("migration_attempted=1") < script.index(
        "render_apply_job migrate"
    )
    assert "schema-bridge-id" in script
    assert "restore_original_service" in script
    assert 'image.digest=${HELM_IMAGE_DIGEST}' in script
    assert "HELM_SOURCE_SHA must be a full Git commit SHA" in script
    assert '--source-sha "$HELM_SOURCE_SHA"' in script
    assert "frontend_release.py chart-schema" in script
    assert '--values "$CHART_PATH/values.yaml"' in script
    assert '--values "$HELM_VALUES_FILE"' in script
    assert "helm_release_contract.py plan" in script
    assert "helm_release_contract.py verify-target" in script
    assert '--bridge-contract "$BRIDGE_SCHEMA_CONTRACT"' in script
    assert "DEPLOYED_IMAGE" in script
    assert "HELM_EVIDENCE_FILE" in script
    assert "HELM_FINAL_MANIFEST_FILE" in script
    assert "write-release-manifest" in script
    assert "HELM_BUILD_PROVENANCE_FILE" in script
    assert "HELM_BRIDGE_BUILD_PROVENANCE_FILE" in script
    assert "verify-build-provenance" in script
    assert '--build-provenance "$HELM_BUILD_PROVENANCE_FILE"' in script
    assert "azure_rollout_lease.py" in script
    assert "checkpoint --mode deploy" in script
    assert "bridge_customer_degraded" in script
    assert 'customer_mode:(if $bridgeRouted then "degraded_read_only"' in script
    assert 'page_owner:(if $bridgeRouted then "platform-engineering"' in script
