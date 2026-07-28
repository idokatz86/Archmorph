#!/usr/bin/env bash
# Serialized, fail-closed Helm owner for Archmorph releases.
set -euo pipefail

: "${HELM_RELEASE_NAME:?HELM_RELEASE_NAME is required}"
: "${HELM_NAMESPACE:?HELM_NAMESPACE is required}"
: "${HELM_VALUES_FILE:?HELM_VALUES_FILE is required}"
: "${HELM_IMAGE_REPOSITORY:?HELM_IMAGE_REPOSITORY is required}"
: "${HELM_IMAGE_DIGEST:?HELM_IMAGE_DIGEST is required}"
: "${HELM_EVIDENCE_FILE:?HELM_EVIDENCE_FILE is required}"
: "${HELM_SOURCE_SHA:?HELM_SOURCE_SHA is required}"

CHART_PATH="${HELM_CHART_PATH:-charts/archmorph}"
LOCK_NAME="${HELM_LOCK_NAME:-${HELM_RELEASE_NAME}-release-lock}"
LOCK_HOLDER="${GITHUB_RUN_ID:-operator}-$(date +%s)"
SCHEMA_CONTRACT=$(mktemp)
python scripts/frontend_release.py chart-schema \
  --values "$CHART_PATH/values.yaml" \
  --output "$SCHEMA_CONTRACT"
EXPECTED_HEAD=$(jq -er '.expected_head' "$SCHEMA_CONTRACT")
mapfile -t ACCEPTED_REVISIONS < <(jq -er '.accepted_current[]' "$SCHEMA_CONTRACT")

if ! [[ "$HELM_IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "HELM_IMAGE_DIGEST must be an immutable sha256 digest" >&2
  exit 1
fi
if ! [[ "$HELM_SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "HELM_SOURCE_SHA must be a full Git commit SHA" >&2
  exit 1
fi
if [[ -z "$EXPECTED_HEAD" || ${#ACCEPTED_REVISIONS[@]} -eq 0 ]]; then
  echo "Chart migration schema contract is incomplete" >&2
  exit 1
fi

release_lock_acquired=0
cleanup() {
  local original_exit=$?
  rm -f "$SCHEMA_CONTRACT"
  if [[ "$release_lock_acquired" -eq 1 ]]; then
    current_holder=$(kubectl -n "$HELM_NAMESPACE" get lease "$LOCK_NAME" \
      -o jsonpath='{.spec.holderIdentity}' 2>/dev/null || true)
    if [[ "$current_holder" == "$LOCK_HOLDER" ]]; then
      kubectl -n "$HELM_NAMESPACE" delete lease "$LOCK_NAME" \
        --ignore-not-found >/dev/null 2>&1 || true
    fi
  fi
  exit "$original_exit"
}
trap cleanup EXIT

if ! cat <<EOF | kubectl -n "$HELM_NAMESPACE" create -f - >/dev/null 2>&1
apiVersion: coordination.k8s.io/v1
kind: Lease
metadata:
  name: ${LOCK_NAME}
spec:
  holderIdentity: ${LOCK_HOLDER}
EOF
then
  echo "Another serialized Helm release owns lease ${HELM_NAMESPACE}/${LOCK_NAME}" >&2
  exit 1
fi
release_lock_acquired=1

USE_EXTERNAL_SECRETS="${HELM_EXTERNAL_SECRETS_ENABLED:-false}"
if [[ "$USE_EXTERNAL_SECRETS" == "true" ]]; then
  if ! kubectl api-resources --api-group=external-secrets.io -o name \
    | grep -qx 'externalsecrets.external-secrets.io'; then
    echo "External Secrets controller CRD is unavailable; release cannot materialize runtime secrets" >&2
    exit 1
  fi
  : "${HELM_EXTERNAL_SECRET_MANIFEST:?HELM_EXTERNAL_SECRET_MANIFEST is required}"
  : "${HELM_EXTERNAL_SECRET_NAME:?HELM_EXTERNAL_SECRET_NAME is required}"
  kubectl -n "$HELM_NAMESPACE" apply -f "$HELM_EXTERNAL_SECRET_MANIFEST"
  kubectl -n "$HELM_NAMESPACE" wait \
    --for=condition=Ready=True "externalsecret/${HELM_EXTERNAL_SECRET_NAME}" \
    --timeout="${HELM_SECRET_TIMEOUT:-180s}"
else
  : "${HELM_EXISTING_SECRET_NAME:?HELM_EXISTING_SECRET_NAME is required}"
fi

RUNTIME_SECRET="${HELM_EXISTING_SECRET_NAME:-${HELM_EXTERNAL_SECRET_NAME:-}}"
SECRET_JSON=$(kubectl -n "$HELM_NAMESPACE" get secret "$RUNTIME_SECRET" -o json)
for key in DATABASE_URL REDIS_URL ARCHMORPH_ADMIN_KEY ARCHMORPH_API_KEY ARCHMORPH_API_KEY_PRINCIPAL_ID JWT_SECRET; do
  if ! jq -e --arg key "$key" '.data[$key] | type == "string" and length > 0' <<<"$SECRET_JSON" >/dev/null; then
    echo "Runtime Secret ${HELM_NAMESPACE}/${RUNTIME_SECRET} is missing required key ${key}" >&2
    exit 1
  fi
done

HELM_ARGS=(
  upgrade --install "$HELM_RELEASE_NAME" "$CHART_PATH"
  --namespace "$HELM_NAMESPACE"
  --values "$HELM_VALUES_FILE"
  --atomic --wait --timeout "${HELM_TIMEOUT:-15m}"
  --set-string "image.repository=${HELM_IMAGE_REPOSITORY}"
  --set-string "image.digest=${HELM_IMAGE_DIGEST}"
  --set-string "migrations.expectedAlembicHead=${EXPECTED_HEAD}"
)
# The owner already reconciled ExternalSecret when requested. Render the chart
# against the now-verified Secret so Helm cannot recreate or race that object.
HELM_ARGS+=(--set externalSecrets.enabled=false --set-string "existingSecret.name=${RUNTIME_SECRET}")
helm "${HELM_ARGS[@]}"

DEPLOYED_IMAGE=$(kubectl -n "$HELM_NAMESPACE" get deployment \
  -l "app.kubernetes.io/instance=${HELM_RELEASE_NAME}" \
  -o jsonpath='{.items[0].spec.template.spec.containers[0].image}')
EXPECTED_IMAGE="${HELM_IMAGE_REPOSITORY}@${HELM_IMAGE_DIGEST}"
if [[ "$DEPLOYED_IMAGE" != "$EXPECTED_IMAGE" ]]; then
  echo "Deployed image ${DEPLOYED_IMAGE} does not match immutable contract ${EXPECTED_IMAGE}" >&2
  exit 1
fi

jq -n \
  --arg release "$HELM_RELEASE_NAME" \
  --arg namespace "$HELM_NAMESPACE" \
  --arg image "$DEPLOYED_IMAGE" \
  --arg expectedHead "$EXPECTED_HEAD" \
  --arg sourceSha "$HELM_SOURCE_SHA" \
  --argjson accepted "$(printf '%s\n' "${ACCEPTED_REVISIONS[@]}" | jq -R . | jq -s .)" \
  '{schema_version:1,status:"released",release:$release,namespace:$namespace,image:$image,source_sha:$sourceSha,expected_head:$expectedHead,accepted_current:$accepted}' \
  > "$HELM_EVIDENCE_FILE"
