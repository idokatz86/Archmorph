"""Executable Helm release owner workflow contracts."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "helm-release.yml"
SCRIPT = ROOT / "scripts" / "helm_release.sh"


def test_helm_release_owner_serializes_and_records_evidence():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert workflow["concurrency"] == {
        "group": "production-backend-rollout",
        "cancel-in-progress": False,
    }
    release = workflow["jobs"]["release"]
    names = [step.get("name") for step in release["steps"]]
    assert names.index("Azure Login (OIDC)") < names.index("Acquire cluster credentials")
    assert names.index("Acquire cluster credentials") < names.index(
        "Run serialized atomic Helm release"
    )
    assert names.index("Run serialized atomic Helm release") < names.index(
        "Upload Helm release evidence"
    )


def test_helm_release_script_is_atomic_secret_aware_and_digest_pinned():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "coordination.k8s.io/v1" in script
    assert 'kubectl -n "$HELM_NAMESPACE" create -f -' in script
    assert "Another serialized Helm release owns lease" in script
    assert "kubectl api-resources --api-group=external-secrets.io" in script
    assert "External Secrets controller CRD is unavailable" in script
    assert "wait" in script and "condition=Ready=True" in script
    assert "get secret" in script
    assert "DATABASE_URL REDIS_URL" in script
    assert 'helm "${HELM_ARGS[@]}"' in script
    assert "--set externalSecrets.enabled=false" in script
    assert "upgrade --install" in script
    assert "--atomic --wait" in script
    assert 'image.digest=${HELM_IMAGE_DIGEST}' in script
    assert "HELM_SOURCE_SHA must be a full Git commit SHA" in script
    assert "source_sha:$sourceSha" in script
    assert "frontend_release.py chart-schema" in script
    assert ".accepted_current[]" in script
    assert "DEPLOYED_IMAGE" in script
    assert "HELM_EVIDENCE_FILE" in script
