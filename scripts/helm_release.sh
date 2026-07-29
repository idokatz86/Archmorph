#!/usr/bin/env bash
# Serialized, schema-bound Helm owner. Migration and workload phases never share
# a Helm transaction, so a committed schema cannot trigger an incompatible rollback.
set -euo pipefail

: "${HELM_RELEASE_NAME:?HELM_RELEASE_NAME is required}"
: "${HELM_NAMESPACE:?HELM_NAMESPACE is required}"
: "${HELM_VALUES_FILE:?HELM_VALUES_FILE is required}"
: "${HELM_IMAGE_REPOSITORY:?HELM_IMAGE_REPOSITORY is required}"
: "${HELM_IMAGE_DIGEST:?HELM_IMAGE_DIGEST is required}"
: "${HELM_EVIDENCE_FILE:?HELM_EVIDENCE_FILE is required}"
: "${HELM_FINAL_MANIFEST_FILE:?HELM_FINAL_MANIFEST_FILE is required}"
: "${HELM_SOURCE_SHA:?HELM_SOURCE_SHA is required}"
: "${RELEASE_MANIFEST_HMAC_KEY:?RELEASE_MANIFEST_HMAC_KEY is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required for release identity}"
: "${GITHUB_WORKFLOW:?GITHUB_WORKFLOW is required for release identity}"
: "${GITHUB_RUN_ID:?GITHUB_RUN_ID is required for release identity}"
: "${GITHUB_RUN_ATTEMPT:?GITHUB_RUN_ATTEMPT is required for release identity}"

CHART_PATH="${HELM_CHART_PATH:-charts/archmorph}"
TARGET_SCHEMA_CONTRACT="${HELM_SCHEMA_CONTRACT_FILE:-backend/schema-contract.json}"
BRIDGE_SCHEMA_CONTRACT="${HELM_BRIDGE_SCHEMA_CONTRACT_FILE:-backend/bridge-schema-contract.json}"
LOCK_NAME="${HELM_LOCK_NAME:-${HELM_RELEASE_NAME}-release-lock}"
LOCK_HOLDER="${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}-$$-$(date +%s)"
LEASE_DURATION_SECONDS="${HELM_LEASE_DURATION_SECONDS:-60}"
LEASE_RENEW_SECONDS="${HELM_LEASE_RENEW_SECONDS:-15}"
EXPECTED_IMAGE="${HELM_IMAGE_REPOSITORY}@${HELM_IMAGE_DIGEST}"
EXECUTION_ID="run-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
EXECUTION_ID="${EXECUTION_ID:0:40}"
WORK_DIR=$(mktemp -d)
MIGRATION_CONTRACT="$WORK_DIR/migration-contract.json"
PLAN_FILE="$WORK_DIR/release-plan.json"
lease_acquired=0
heartbeat_pid=""
release_completed=0
schema_committed=0
migration_attempted=0
bridge_routed=0
bridge_created=0
bridge_deployment=""
service_name=""
original_selector_b64=""
previous_image=""
observed_schema=""
failure_action="preserve_pre_migration_service"

if ! [[ "$HELM_IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "HELM_IMAGE_DIGEST must be an immutable sha256 digest" >&2
  exit 1
fi
if ! [[ "$HELM_SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "HELM_SOURCE_SHA must be a full Git commit SHA" >&2
  exit 1
fi
if [[ ${#RELEASE_MANIFEST_HMAC_KEY} -lt 32 ]]; then
  echo "RELEASE_MANIFEST_HMAC_KEY must contain at least 32 bytes" >&2
  exit 1
fi

python scripts/frontend_release.py chart-schema \
  --values "$CHART_PATH/values.yaml" \
  --values "$HELM_VALUES_FILE" \
  --output "$MIGRATION_CONTRACT"
EXPECTED_HEAD=$(jq -er '.expected_head' "$MIGRATION_CONTRACT")
TARGET_CONTRACT_DIGEST=$(python scripts/helm_release_contract.py contract-digest \
  --contract "$TARGET_SCHEMA_CONTRACT")
BRIDGE_CONTRACT_DIGEST=$(python scripts/helm_release_contract.py contract-digest \
  --contract "$BRIDGE_SCHEMA_CONTRACT")

write_evidence() {
  local evidence_status="$1"
  local plan_json='{}'
  local committed_json=false
  local attempted_json=false
  local bridge_json=false
  if [[ -s "$PLAN_FILE" ]]; then
    plan_json=$(cat "$PLAN_FILE")
  fi
  [[ "$schema_committed" -eq 1 ]] && committed_json=true
  [[ "$migration_attempted" -eq 1 ]] && attempted_json=true
  [[ "$bridge_routed" -eq 1 ]] && bridge_json=true
  jq -n \
    --arg status "$evidence_status" \
    --arg release "$HELM_RELEASE_NAME" \
    --arg namespace "$HELM_NAMESPACE" \
    --arg holder "$LOCK_HOLDER" \
    --arg image "$EXPECTED_IMAGE" \
    --arg previousImage "$previous_image" \
    --arg sourceSha "$HELM_SOURCE_SHA" \
    --arg observedSchema "$observed_schema" \
    --arg targetSchema "$EXPECTED_HEAD" \
    --arg targetContractDigest "$TARGET_CONTRACT_DIGEST" \
    --arg failureAction "$failure_action" \
    --argjson schemaCommitted "$committed_json" \
    --argjson migrationAttempted "$attempted_json" \
    --argjson bridgeRouted "$bridge_json" \
    --argjson plan "$plan_json" \
    '{schema_version:2,status:$status,release:$release,namespace:$namespace,
      lease_holder:$holder,target_image:$image,previous_image:$previousImage,
      source_sha:$sourceSha,observed_schema:$observedSchema,target_schema:$targetSchema,
      target_contract_digest:$targetContractDigest,migration_attempted:$migrationAttempted,
      schema_committed:$schemaCommitted,
      bridge_routed:$bridgeRouted,failure_action:$failureAction,plan:$plan}' \
    > "${HELM_EVIDENCE_FILE}.tmp"
  mv "${HELM_EVIDENCE_FILE}.tmp" "$HELM_EVIDENCE_FILE"
}

lease_args=(
  --namespace "$HELM_NAMESPACE"
  --name "$LOCK_NAME"
  --holder "$LOCK_HOLDER"
  --duration-seconds "$LEASE_DURATION_SECONDS"
)

restore_original_service() {
  if [[ "$bridge_routed" -ne 1 || -z "$service_name" || -z "$original_selector_b64" ]]; then
    return 0
  fi
  printf '%s' "$original_selector_b64" | base64 --decode > "$WORK_DIR/original-selector.json"
  jq -e 'type == "object" and length > 0 and all(to_entries[];
    (.key | type == "string" and length > 0) and
    (.value | type == "string" and length > 0))' \
    "$WORK_DIR/original-selector.json" >/dev/null
  selector_patch=$(jq -c '[{"op":"replace","path":"/spec/selector","value":.}]' \
    "$WORK_DIR/original-selector.json")
  kubectl -n "$HELM_NAMESPACE" patch service "$service_name" \
    --type=json -p "$selector_patch"
  kubectl -n "$HELM_NAMESPACE" annotate service "$service_name" \
    archmorph.io/schema-bridge-id- archmorph.io/original-selector-b64- >/dev/null
  bridge_routed=0
}

cleanup() {
  local original_exit=$?
  trap - EXIT TERM INT
  if [[ -n "$heartbeat_pid" ]]; then
    kill "$heartbeat_pid" >/dev/null 2>&1 || true
    wait "$heartbeat_pid" >/dev/null 2>&1 || true
  fi
  if [[ "$release_completed" -ne 1 ]]; then
    if [[ "$migration_attempted" -eq 1 && "$schema_committed" -eq 0 && "$bridge_routed" -eq 1 ]]; then
      failure_action="retain_bridge_migration_outcome_requires_recovery"
    elif [[ "$schema_committed" -eq 0 && "$bridge_routed" -eq 1 ]]; then
      restore_original_service || failure_action="retain_bridge_manual_recovery"
    fi
    if [[ "$schema_committed" -eq 0 && "$bridge_created" -eq 1 && "$bridge_routed" -eq 0 ]]; then
      kubectl -n "$HELM_NAMESPACE" delete deployment "$bridge_deployment" \
        --ignore-not-found --wait=false >/dev/null 2>&1 || true
    fi
    write_evidence "failed"
  fi
  if [[ "$lease_acquired" -eq 1 ]]; then
    python scripts/kubernetes_lease.py "${lease_args[@]}" release >/dev/null || true
  fi
  rm -rf "$WORK_DIR"
  exit "$original_exit"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

write_evidence "starting"
python scripts/kubernetes_lease.py "${lease_args[@]}" acquire \
  --wait-seconds "${HELM_LEASE_WAIT_SECONDS:-120}" \
  --retry-seconds "${HELM_LEASE_RETRY_SECONDS:-2}" >/dev/null
lease_acquired=1
python scripts/kubernetes_lease.py "${lease_args[@]}" heartbeat \
  --interval-seconds "$LEASE_RENEW_SECONDS" \
  --max-failures 3 \
  --parent-pid $$ &
heartbeat_pid=$!

assert_lease() {
  if ! kill -0 "$heartbeat_pid" >/dev/null 2>&1; then
    echo "Helm release Lease heartbeat is not running" >&2
    exit 1
  fi
  python scripts/kubernetes_lease.py "${lease_args[@]}" renew --max-conflicts 3 >/dev/null
}

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
  if ! jq -e --arg key "$key" '.data[$key] | type == "string" and length > 0' \
    <<<"$SECRET_JSON" >/dev/null; then
    echo "Runtime Secret ${HELM_NAMESPACE}/${RUNTIME_SECRET} is missing required key ${key}" >&2
    exit 1
  fi
done

DEPLOYMENTS=$(kubectl -n "$HELM_NAMESPACE" get deployment \
  -l "app.kubernetes.io/instance=${HELM_RELEASE_NAME}" -o json)
if [[ $(jq '.items | length' <<<"$DEPLOYMENTS") -ne 1 ]]; then
  echo "Helm release requires exactly one existing workload Deployment" >&2
  exit 1
fi
DEPLOYMENT_NAME=$(jq -er '.items[0].metadata.name' <<<"$DEPLOYMENTS")
previous_image=$(jq -er '.items[0].spec.template.spec.containers[0].image' <<<"$DEPLOYMENTS")
EXPECTED_WORKLOAD_SELECTOR=$(jq -cS '.items[0].spec.selector.matchLabels' \
  <<<"$DEPLOYMENTS")
SERVICES=$(kubectl -n "$HELM_NAMESPACE" get service \
  -l "app.kubernetes.io/instance=${HELM_RELEASE_NAME}" -o json)
if [[ $(jq '.items | length' <<<"$SERVICES") -ne 1 ]]; then
  echo "Helm release requires exactly one workload Service" >&2
  exit 1
fi
service_name=$(jq -er '.items[0].metadata.name' <<<"$SERVICES")
SERVICE_JSON=$(jq '.items[0]' <<<"$SERVICES")
ACTIVE_BRIDGE_ID=$(jq -r '.spec.selector["archmorph.io/schema-bridge-id"] // ""' \
  <<<"$SERVICE_JSON")

ready_pod_for_selector() {
  local selector="$1"
  kubectl -n "$HELM_NAMESPACE" get pod -l "$selector" -o json \
    | jq -er '[.items[] | select(any(.status.conditions[]?;
        .type == "Ready" and .status == "True"))][0].metadata.name'
}

wait_for_service_endpoint() {
  local endpoint_service="$1"
  for attempt in $(seq 1 30); do
    if kubectl -n "$HELM_NAMESPACE" get endpoints "$endpoint_service" -o json \
      | jq -e 'any(.subsets[]?.addresses[]?; .ip | type == "string" and length > 0)' \
        >/dev/null; then
      return 0
    fi
    if [[ "$attempt" -lt 30 ]]; then
      sleep 2
    fi
  done
  echo "Service ${HELM_NAMESPACE}/${endpoint_service} has no ready endpoint" >&2
  return 1
}

probe_runtime() {
  local pod_name="$1"
  local output_file="$2"
  kubectl -n "$HELM_NAMESPACE" exec "$pod_name" -- python -c \
    'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/api/schema-compatibility", timeout=10).read().decode())' \
    > "$output_file"
  jq -e '.status == "compatible"' "$output_file" >/dev/null
}

if [[ -n "$ACTIVE_BRIDGE_ID" ]]; then
  if ! [[ "$ACTIVE_BRIDGE_ID" =~ ^[a-z0-9][a-z0-9-]{0,39}$ ]]; then
    echo "Active schema bridge selector identity is malformed" >&2
    exit 1
  fi
  bridge_routed=1
  original_selector_b64=$(jq -er \
    '.metadata.annotations["archmorph.io/original-selector-b64"]' <<<"$SERVICE_JSON")
  RETAINED_SELECTOR=$(printf '%s' "$original_selector_b64" | base64 --decode | jq -cS .)
  if [[ "$RETAINED_SELECTOR" != "$EXPECTED_WORKLOAD_SELECTOR" ]]; then
    echo "Retained schema bridge original selector does not match the workload Deployment" >&2
    exit 1
  fi
  BRIDGE_POD=$(ready_pod_for_selector "archmorph.io/schema-bridge-id=${ACTIVE_BRIDGE_ID}")
  probe_runtime "$BRIDGE_POD" "$WORK_DIR/previous-runtime.json"
  previous_image=$(kubectl -n "$HELM_NAMESPACE" get pod "$BRIDGE_POD" \
    -o jsonpath='{.spec.containers[0].image}')
else
  CURRENT_SERVICE_SELECTOR=$(jq -cS '.spec.selector' <<<"$SERVICE_JSON")
  if [[ "$CURRENT_SERVICE_SELECTOR" != "$EXPECTED_WORKLOAD_SELECTOR" ]]; then
    echo "Workload Service selector does not match the Helm Deployment" >&2
    exit 1
  fi
  DEPLOYMENT_SELECTOR=$(jq -r '.items[0].spec.selector.matchLabels | to_entries |
    map("\(.key)=\(.value)") | join(",")' <<<"$DEPLOYMENTS")
  PREVIOUS_POD=$(ready_pod_for_selector "$DEPLOYMENT_SELECTOR")
  probe_runtime "$PREVIOUS_POD" "$WORK_DIR/previous-runtime.json"
fi

observed_schema=$(jq -er '.current_revision' "$WORK_DIR/previous-runtime.json")
if [[ "$observed_schema" == "$EXPECTED_HEAD" ]]; then
  schema_committed=1
fi
PREVIOUS_ACCEPTS_TARGET=$(jq -r --arg target "$EXPECTED_HEAD" \
  '(.accepted_revisions | index($target)) != null' "$WORK_DIR/previous-runtime.json")
PREVIOUS_ROLE=$(jq -er '.release_role' "$WORK_DIR/previous-runtime.json")

if [[ "$PREVIOUS_ROLE" != "bridge" && "$PREVIOUS_ACCEPTS_TARGET" != "true" ]]; then
  : "${HELM_BRIDGE_IMAGE_REPOSITORY:?An incompatible prior image requires HELM_BRIDGE_IMAGE_REPOSITORY}"
  : "${HELM_BRIDGE_IMAGE_DIGEST:?An incompatible prior image requires HELM_BRIDGE_IMAGE_DIGEST}"
  if ! [[ "$HELM_BRIDGE_IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "HELM_BRIDGE_IMAGE_DIGEST must be immutable" >&2
    exit 1
  fi
  BRIDGE_IMAGE="${HELM_BRIDGE_IMAGE_REPOSITORY}@${HELM_BRIDGE_IMAGE_DIGEST}"
  bridge_deployment="${HELM_RELEASE_NAME}-schema-bridge-${EXECUTION_ID}"
  bridge_deployment="${bridge_deployment:0:63}"
  jq --arg name "$bridge_deployment" --arg namespace "$HELM_NAMESPACE" \
    --arg image "$BRIDGE_IMAGE" --arg bridgeId "$EXECUTION_ID" \
    --arg sourceSha "$HELM_SOURCE_SHA" \
    --arg contractDigest "$BRIDGE_CONTRACT_DIGEST" '
      .items[0]
      | del(.status)
      | .metadata = {name:$name,namespace:$namespace,labels:{"archmorph.io/schema-bridge-id":$bridgeId}}
      | .spec.replicas = 1
      | .spec.strategy = {type:"Recreate"}
      | .spec.selector.matchLabels = {"archmorph.io/schema-bridge-id":$bridgeId}
      | .spec.template.metadata = {labels:{"archmorph.io/schema-bridge-id":$bridgeId}}
      | .spec.template.spec.containers[0].image = $image
      | .spec.template.spec.containers[0].env = ((.spec.template.spec.containers[0].env // [])
          | map(select(.name != "ARCHMORPH_RELEASE_ROLE"
              and .name != "ARCHMORPH_SOURCE_SHA"
              and .name != "ARCHMORPH_SCHEMA_CONTRACT_DIGEST"))
          + [
              {name:"ARCHMORPH_RELEASE_ROLE",value:"bridge"},
              {name:"ARCHMORPH_SOURCE_SHA",value:$sourceSha},
              {name:"ARCHMORPH_SCHEMA_CONTRACT_DIGEST",value:$contractDigest}
            ])
    ' <<<"$DEPLOYMENTS" > "$WORK_DIR/bridge-deployment.json"
  kubectl -n "$HELM_NAMESPACE" apply -f "$WORK_DIR/bridge-deployment.json"
  bridge_created=1
  kubectl -n "$HELM_NAMESPACE" rollout status "deployment/${bridge_deployment}" \
    --timeout="${HELM_BRIDGE_TIMEOUT:-5m}"
  BRIDGE_POD=$(ready_pod_for_selector "archmorph.io/schema-bridge-id=${EXECUTION_ID}")
  probe_runtime "$BRIDGE_POD" "$WORK_DIR/bridge-runtime.json"
  python scripts/helm_release_contract.py plan \
    --previous-runtime "$WORK_DIR/previous-runtime.json" \
    --target-contract "$TARGET_SCHEMA_CONTRACT" \
    --migration-contract "$MIGRATION_CONTRACT" \
    --bridge-runtime "$WORK_DIR/bridge-runtime.json" \
    --bridge-contract "$BRIDGE_SCHEMA_CONTRACT" \
    --output "$PLAN_FILE" >/dev/null
  original_selector_b64=$(jq -c '.spec.selector' <<<"$SERVICE_JSON" | base64 | tr -d '\n')
  kubectl -n "$HELM_NAMESPACE" annotate service "$service_name" \
    "archmorph.io/original-selector-b64=${original_selector_b64}" \
    "archmorph.io/schema-bridge-id=${EXECUTION_ID}" --overwrite >/dev/null
  bridge_patch=$(jq -nc --arg bridgeId "$EXECUTION_ID" \
    '[{"op":"replace","path":"/spec/selector","value":{"archmorph.io/schema-bridge-id":$bridgeId}}]')
  kubectl -n "$HELM_NAMESPACE" patch service "$service_name" --type=json -p "$bridge_patch"
  bridge_routed=1
  wait_for_service_endpoint "$service_name"
else
  python scripts/helm_release_contract.py plan \
    --previous-runtime "$WORK_DIR/previous-runtime.json" \
    --target-contract "$TARGET_SCHEMA_CONTRACT" \
    --migration-contract "$MIGRATION_CONTRACT" \
    --bridge-contract "$BRIDGE_SCHEMA_CONTRACT" \
    --output "$PLAN_FILE" >/dev/null
fi
failure_action=$(jq -er '.post_migration_failure_action' "$PLAN_FILE")
assert_lease

render_apply_job() {
  local phase="$1"
  local template="$2"
  local manifest="$WORK_DIR/${phase}.yaml"
  helm template "$HELM_RELEASE_NAME" "$CHART_PATH" \
    --namespace "$HELM_NAMESPACE" \
    --values "$HELM_VALUES_FILE" \
    --set-string "image.repository=${HELM_IMAGE_REPOSITORY}" \
    --set-string "image.digest=${HELM_IMAGE_DIGEST}" \
    --set-string "releaseEvidence.sourceSha=${HELM_SOURCE_SHA}" \
    --set-string "releaseEvidence.schemaContractDigest=${TARGET_CONTRACT_DIGEST}" \
    --set externalSecrets.enabled=false \
    --set-string "existingSecret.name=${RUNTIME_SECRET}" \
    --set-string "migrations.phase=${phase}" \
    --set-string "migrations.executionId=${EXECUTION_ID}" \
    --show-only "$template" > "$manifest"
  job_service_account=$(python - "$manifest" <<'PY'
import sys
import yaml

documents = [item for item in yaml.safe_load_all(open(sys.argv[1], encoding="utf-8")) if item]
if len(documents) != 1 or documents[0].get("kind") != "Job":
    raise SystemExit("release phase render did not contain exactly one Job")
service_account = documents[0].get("spec", {}).get("template", {}).get("spec", {}).get("serviceAccountName")
if not isinstance(service_account, str) or not service_account:
    raise SystemExit("release phase Job has no explicit ServiceAccount")
print(service_account)
PY
  )
  kubectl -n "$HELM_NAMESPACE" get serviceaccount "$job_service_account" -o json \
    > "$WORK_DIR/${phase}-service-account.json"
  job_ref=$(kubectl -n "$HELM_NAMESPACE" apply -f "$manifest" -o name)
  kubectl -n "$HELM_NAMESPACE" wait --for=condition=complete "$job_ref" \
    --timeout="${HELM_MIGRATION_TIMEOUT:-15m}"
}

render_apply_job preflight templates/migration-secret-preflight.yaml
assert_lease
migration_attempted=1
render_apply_job migrate templates/migration-job.yaml
schema_committed=1

if [[ "$bridge_routed" -eq 1 ]]; then
  PROTECTION_POD=$(ready_pod_for_selector \
    "archmorph.io/schema-bridge-id=${ACTIVE_BRIDGE_ID:-$EXECUTION_ID}")
else
  PROTECTION_POD="$PREVIOUS_POD"
fi
probe_runtime "$PROTECTION_POD" "$WORK_DIR/post-migration-runtime.json"
observed_schema=$(jq -er '.current_revision' "$WORK_DIR/post-migration-runtime.json")
if [[ "$observed_schema" != "$EXPECTED_HEAD" ]]; then
  echo "Migration Job completed but protected runtime observed ${observed_schema}, expected ${EXPECTED_HEAD}" >&2
  exit 1
fi
assert_lease

# Workload-only phase: deliberately no --atomic and migrations are disabled.
# Failure is explicit fix-forward while a schema-compatible path remains serving.
helm upgrade --install "$HELM_RELEASE_NAME" "$CHART_PATH" \
  --namespace "$HELM_NAMESPACE" \
  --values "$HELM_VALUES_FILE" \
  --wait --timeout "${HELM_TIMEOUT:-15m}" \
  --set-string "image.repository=${HELM_IMAGE_REPOSITORY}" \
  --set-string "image.digest=${HELM_IMAGE_DIGEST}" \
  --set-string "releaseEvidence.sourceSha=${HELM_SOURCE_SHA}" \
  --set-string "releaseEvidence.schemaContractDigest=${TARGET_CONTRACT_DIGEST}" \
  --set migrations.enabled=false \
  --set externalSecrets.enabled=false \
  --set-string "existingSecret.name=${RUNTIME_SECRET}"
assert_lease

TARGET_DEPLOYMENT=$(kubectl -n "$HELM_NAMESPACE" get deployment "$DEPLOYMENT_NAME" -o json)
DEPLOYED_IMAGE=$(jq -er '.spec.template.spec.containers[0].image' <<<"$TARGET_DEPLOYMENT")
if [[ "$DEPLOYED_IMAGE" != "$EXPECTED_IMAGE" ]]; then
  echo "Deployed image ${DEPLOYED_IMAGE} does not match immutable contract ${EXPECTED_IMAGE}" >&2
  exit 1
fi
DEPLOYED_ENV=$(jq -c '.spec.template.spec.containers[0].env // []' \
  <<<"$TARGET_DEPLOYMENT")
if ! jq -e \
  --arg source "$HELM_SOURCE_SHA" \
  --arg digest "$TARGET_CONTRACT_DIGEST" '
    any(.[]; .name == "ARCHMORPH_RELEASE_ROLE" and .value == "final")
    and any(.[]; .name == "ARCHMORPH_SOURCE_SHA" and .value == $source)
    and any(.[]; .name == "ARCHMORPH_SCHEMA_CONTRACT_DIGEST" and .value == $digest)
  ' <<<"$DEPLOYED_ENV" >/dev/null; then
  echo "Deployed workload release evidence metadata does not match the target" >&2
  exit 1
fi
TARGET_SELECTOR=$(jq -r '.spec.selector.matchLabels | to_entries |
  map("\(.key)=\(.value)") | join(",")' <<<"$TARGET_DEPLOYMENT")
TARGET_POD=$(ready_pod_for_selector "$TARGET_SELECTOR")
probe_runtime "$TARGET_POD" "$WORK_DIR/target-runtime.json"
python scripts/helm_release_contract.py verify-target \
  --runtime "$WORK_DIR/target-runtime.json" \
  --target-contract "$TARGET_SCHEMA_CONTRACT" \
  --expected-schema "$EXPECTED_HEAD" >/dev/null

if [[ "$bridge_routed" -eq 1 ]]; then
  restore_original_service
  wait_for_service_endpoint "$service_name"
  kubectl -n "$HELM_NAMESPACE" rollout status "deployment/${DEPLOYMENT_NAME}" \
    --timeout="${HELM_TIMEOUT:-15m}"
  if [[ "$bridge_created" -eq 1 ]]; then
    kubectl -n "$HELM_NAMESPACE" delete deployment "$bridge_deployment" --wait=false
  fi
fi

python scripts/containerapp_rollout.py write-release-manifest \
  --output "$HELM_FINAL_MANIFEST_FILE" \
  --role final \
  --revision "$DEPLOYMENT_NAME" \
  --image "$EXPECTED_IMAGE" \
  --source-sha "$HELM_SOURCE_SHA" \
  --schema-contract "$TARGET_SCHEMA_CONTRACT" \
  --observed-schema "$EXPECTED_HEAD" \
  --repository "$GITHUB_REPOSITORY" \
  --workflow "$GITHUB_WORKFLOW" \
  --run-id "$GITHUB_RUN_ID" \
  --run-attempt "$GITHUB_RUN_ATTEMPT"
python scripts/containerapp_rollout.py verify-release-manifest \
  --input "$HELM_FINAL_MANIFEST_FILE" \
  --required-role final \
  --expected-repository "$GITHUB_REPOSITORY" \
  --expected-workflow "$GITHUB_WORKFLOW" \
  --expected-run-id "$GITHUB_RUN_ID" \
  --expected-run-attempt "$GITHUB_RUN_ATTEMPT" >/dev/null

failure_action="none"
write_evidence "released"
release_completed=1
