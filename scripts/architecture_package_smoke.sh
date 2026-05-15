#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-}"
FRONTEND_URL="${FRONTEND_URL:-}"
SAMPLE_ID="${SAMPLE_ID:-aws-hub-spoke}"
STRICT_FRESHNESS="${STRICT_FRESHNESS:-false}"
SMOKE_API_KEY="${ARCHMORPH_API_KEY:-${API_KEY:-${ADMIN_KEY:-}}}"
RUN_ID="${GITHUB_RUN_ID:-local}"
COMMIT_SHA="${GITHUB_SHA:-$(git rev-parse --short HEAD 2>/dev/null || echo unknown)}"
ARTIFACT_ROOT="${ARTIFACT_ROOT:-smoke-artifacts/architecture-package/$(date -u +%Y%m%dT%H%M%SZ)}"
HTTP_TIMEOUT="${HTTP_TIMEOUT:-180}"
SECONDARY_FORMAT_SMOKE="${SECONDARY_FORMAT_SMOKE:-true}"

if [[ -z "$API_URL" ]]; then
  echo "::error::API_URL is required"
  exit 1
fi

if [[ -z "$SMOKE_API_KEY" ]]; then
  echo "::error::ARCHMORPH_API_KEY, API_KEY, or ADMIN_KEY is required for the full Architecture Package smoke"
  exit 1
fi

API_BASE="${API_URL%/}"
API_BASE="${API_BASE%/api}/api"
FRONTEND_URL="${FRONTEND_URL%/}"
EXPORT_CAPABILITY=""

mkdir -p "$ARTIFACT_ROOT/raw" "$ARTIFACT_ROOT/artifacts"
SUMMARY="$ARTIFACT_ROOT/summary.md"
MANIFEST="$ARTIFACT_ROOT/manifest.jsonl"

fail() {
  local step_name="$1"
  local message="$2"
  local body_file="${3:-}"
  echo "::error::${step_name}: ${message}"
  {
    echo ""
    echo "## Failure"
    echo ""
    echo "- Step: ${step_name}"
    echo "- Message: ${message}"
    if [[ -n "$body_file" && -f "$body_file" ]]; then
      echo "- Response excerpt:"
      echo '```'
      head -c 1200 "$body_file" || true
      echo
      echo '```'
    fi
  } >> "$SUMMARY"
  exit 1
}

record_step() {
  local step_name="$1"
  local status="$2"
  local detail="$3"
  printf '| %s | %s | %s |\n' "$step_name" "$status" "$detail" >> "$SUMMARY"
}

json_value() {
  local file_path="$1"
  local jq_filter="$2"
  jq -er "$jq_filter" "$file_path" >/dev/null
}

request() {
  local step_name="$1"
  local method="$2"
  local url="$3"
  local output_file="$4"
  local body="${5:-}"
  local headers_file="${output_file}.headers"
  local status_file="${output_file}.status"
  local curl_args=(
    -sS
    -D "$headers_file"
    -o "$output_file"
    -w "%{http_code}"
    --max-time "$HTTP_TIMEOUT"
    -X "$method"
    -H "X-API-Key: ${SMOKE_API_KEY}"
  )

  if [[ -n "$EXPORT_CAPABILITY" ]]; then
    curl_args+=( -H "X-Export-Capability: ${EXPORT_CAPABILITY}" )
  fi

  if [[ -n "$body" ]]; then
    curl_args+=( -H "Content-Type: application/json" -d "$body" )
  fi

  local http_code
  http_code=$(curl "${curl_args[@]}" "$url" || echo "000")
  echo "$http_code" > "$status_file"
  if [[ ! "$http_code" =~ ^2 ]]; then
    fail "$step_name" "HTTP ${http_code} from ${method} ${url}" "$output_file"
  fi

  local next_capability
  next_capability=$(jq -er '.export_capability // empty' "$output_file" 2>/dev/null || true)
  if [[ -z "$next_capability" && -f "$headers_file" ]]; then
    next_capability=$(awk 'tolower($0) ~ /^x-export-capability-next:/ {gsub(/\r/, ""); sub(/^[^:]+:[[:space:]]*/, ""); sub(/[[:space:]]*$/, ""); print; exit}' "$headers_file")
  fi
  if [[ -n "$next_capability" ]]; then
    EXPORT_CAPABILITY="$next_capability"
  fi
}

write_content_artifact() {
  local response_file="$1"
  local jq_filter="$2"
  local artifact_path="$3"
  jq -r "$jq_filter" "$response_file" > "$artifact_path"
  if [[ ! -s "$artifact_path" ]]; then
    fail "artifact-write" "Artifact ${artifact_path} is empty" "$response_file"
  fi
}

validate_svg() {
  local step_name="$1"
  local svg_path="$2"
  local expected_text="$3"
  python3 - "$svg_path" <<'PY'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
root = ET.parse(path).getroot()
if not root.tag.lower().endswith('svg'):
    raise SystemExit(f"root tag is {root.tag}, expected svg")
PY
  grep -qi "$expected_text" "$svg_path" || fail "$step_name" "SVG missing expected text: ${expected_text}" "$svg_path"
}

decode_base64_artifact() {
  local step_name="$1"
  local response_file="$2"
  local artifact_path="$3"
  local expected_magic="$4"
  local min_bytes="$5"
  python3 - "$response_file" "$artifact_path" "$expected_magic" "$min_bytes" <<'PY'
import base64
import json
import sys

response_file, artifact_path, expected_magic, min_bytes = sys.argv[1:]
with open(response_file, encoding="utf-8") as handle:
    payload = json.load(handle)
content_b64 = payload.get("content_b64")
if not isinstance(content_b64, str) or not content_b64:
    raise SystemExit("content_b64 missing")
data = base64.b64decode(content_b64)
if len(data) < int(min_bytes):
    raise SystemExit(f"decoded artifact too small: {len(data)} bytes")
if not data.startswith(expected_magic.encode("latin1")):
    raise SystemExit(f"decoded artifact missing magic bytes {expected_magic!r}")
with open(artifact_path, "wb") as handle:
    handle.write(data)
PY
  if [[ ! -s "$artifact_path" ]]; then
    fail "$step_name" "Decoded artifact ${artifact_path} is empty" "$response_file"
  fi
}

validate_drawio() {
  local drawio_path="$1"
  python3 - "$drawio_path" <<'PY'
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
if root.tag not in {"mxfile", "mxGraphModel"}:
    raise SystemExit(f"unexpected Draw.io root: {root.tag}")
if not root.findall(".//mxCell"):
    raise SystemExit("Draw.io export has no mxCell elements")
PY
}

validate_vdx() {
  local vdx_path="$1"
  python3 - "$vdx_path" <<'PY'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
content = open(path, encoding="utf-8").read()
rest = content.lstrip()
if rest.startswith("<?xml"):
    rest = rest.split("?>", 1)[1]
root_open = rest[: rest.find(">") + 1]
if root_open.count('xmlns="') != 1:
    raise SystemExit(f"VDX root must have exactly one xmlns declaration: {root_open}")
root = ET.fromstring(content)
if not root.tag.endswith("VisioDocument"):
    raise SystemExit(f"unexpected VDX root: {root.tag}")
ns = "{http://schemas.microsoft.com/visio/2003/core}"
pages = root.find(f"{ns}Pages")
if pages is None or not pages.findall(f"{ns}Page"):
    raise SystemExit("VDX export has no Page elements")
PY
}

validate_json_field() {
  local step_name="$1"
  local file_path="$2"
  local jq_filter="$3"
  local message="$4"
  json_value "$file_path" "$jq_filter" || fail "$step_name" "$message" "$file_path"
}

cat > "$SUMMARY" <<EOF
# Architecture Package Production Smoke

- API base: \`${API_BASE}\`
- Frontend: \`${FRONTEND_URL:-not provided}\`
- Sample: \`${SAMPLE_ID}\`
- Strict freshness: \`${STRICT_FRESHNESS}\`
- Secondary formats: \`${SECONDARY_FORMAT_SMOKE}\`
- Commit: \`${COMMIT_SHA}\`
- Run: \`${RUN_ID}\`

| Step | Result | Evidence |
|---|---|---|
EOF

echo "Running Architecture Package smoke against ${API_BASE}"
echo "Artifacts: ${ARTIFACT_ROOT}"

HEALTH_JSON="$ARTIFACT_ROOT/raw/01-health.json"
request "health" GET "${API_BASE}/health" "$HEALTH_JSON"
validate_json_field "health" "$HEALTH_JSON" '.status == "healthy" or .status == "degraded"' "Health status must be healthy or degraded"
if jq -e '.scheduled_jobs[]? | select(.stale == true)' "$HEALTH_JSON" >/dev/null; then
  if [[ "$STRICT_FRESHNESS" == "true" ]]; then
    fail "health" "Scheduled jobs are stale while STRICT_FRESHNESS=true" "$HEALTH_JSON"
  fi
  record_step "Health and scheduled jobs" "warn" "$(jq -rc '[.scheduled_jobs[]? | select(.stale == true) | {name, age_hours, budget_hours}]' "$HEALTH_JSON")"
else
  record_step "Health and scheduled jobs" "pass" "$(jq -rc '{status, service_catalog_refresh, scheduled_jobs}' "$HEALTH_JSON")"
fi

ANALYSIS_JSON="$ARTIFACT_ROOT/raw/02-sample-analysis.json"
request "sample-analysis" POST "${API_BASE}/samples/${SAMPLE_ID}/analyze" "$ANALYSIS_JSON" '{}'
validate_json_field "sample-analysis" "$ANALYSIS_JSON" '.diagram_id | type == "string" and length > 0' "Sample analysis must return diagram_id"
validate_json_field "sample-analysis" "$ANALYSIS_JSON" '(.mappings // []) | length > 0' "Sample analysis must include mappings"
validate_json_field "sample-analysis" "$ANALYSIS_JSON" '(.service_connections // []) | length > 0' "Sample analysis must include service connections"
DIAGRAM_ID=$(jq -r '.diagram_id' "$ANALYSIS_JSON")
record_step "Sample analysis" "pass" "diagram_id=${DIAGRAM_ID}, mappings=$(jq -r '(.mappings // []) | length' "$ANALYSIS_JSON")"

QUESTIONS_JSON="$ARTIFACT_ROOT/raw/03-guided-questions.json"
request "guided-questions" POST "${API_BASE}/diagrams/${DIAGRAM_ID}/questions" "$QUESTIONS_JSON" '{}'
validate_json_field "guided-questions" "$QUESTIONS_JSON" '.diagram_id == "'"$DIAGRAM_ID"'"' "Guided questions must reference the smoke diagram"
record_step "Guided questions" "pass" "questions=$(jq -r '.total // ((.questions // []) | length)' "$QUESTIONS_JSON")"

ANSWERS_BODY='{
  "arch_deploy_region": "West Europe",
  "arch_ha": "Multi-region active-passive (99.99 %)",
  "sec_compliance": "GDPR",
  "sec_network_isolation": "Full private endpoints",
  "arch_sku_strategy": "Balanced (good performance-to-cost ratio)"
}'
ANSWERS_JSON="$ARTIFACT_ROOT/raw/04-apply-answers.json"
request "apply-answers" POST "${API_BASE}/diagrams/${DIAGRAM_ID}/apply-answers" "$ANSWERS_JSON" "$ANSWERS_BODY"
validate_json_field "apply-answers" "$ANSWERS_JSON" '.customer_intent | type == "object"' "Applied answers must create customer_intent"
validate_json_field "apply-answers" "$ANSWERS_JSON" '.iac_parameters.deploy_region == "westeurope"' "Applied answers must persist deploy_region=westeurope"
validate_json_field "apply-answers" "$ANSWERS_JSON" '.iac_parameters.network_isolation == "Full private endpoints"' "Applied answers must persist network isolation"
validate_json_field "apply-answers" "$ANSWERS_JSON" '.iac_parameters.sku_strategy == "Balanced (good performance-to-cost ratio)"' "Applied answers must persist SKU strategy"
record_step "Apply guided answers" "pass" "customer_intent and iac_parameters persisted"

IAC_JSON="$ARTIFACT_ROOT/raw/05-iac.json"
request "iac" POST "${API_BASE}/diagrams/${DIAGRAM_ID}/generate?format=terraform&force=true" "$IAC_JSON" '{}'
validate_json_field "iac" "$IAC_JSON" '.code | type == "string" and length > 80' "IaC response must include non-empty Terraform code"
write_content_artifact "$IAC_JSON" '.code' "$ARTIFACT_ROOT/artifacts/archmorph-iac.tf"
grep -Eq 'resource |module |provider ' "$ARTIFACT_ROOT/artifacts/archmorph-iac.tf" || fail "iac" "Terraform output lacks provider/resource/module content" "$ARTIFACT_ROOT/artifacts/archmorph-iac.tf"
record_step "IaC Terraform" "pass" "artifacts/archmorph-iac.tf ($(wc -c < "$ARTIFACT_ROOT/artifacts/archmorph-iac.tf") bytes)"

HLD_JSON="$ARTIFACT_ROOT/raw/06-hld.json"
request "hld" POST "${API_BASE}/diagrams/${DIAGRAM_ID}/generate-hld" "$HLD_JSON" '{}'
validate_json_field "hld" "$HLD_JSON" '.markdown | type == "string" and length > 200' "HLD must include non-empty markdown"
write_content_artifact "$HLD_JSON" '.markdown' "$ARTIFACT_ROOT/artifacts/hld.md"
grep -qi 'Azure' "$ARTIFACT_ROOT/artifacts/hld.md" || fail "hld" "HLD markdown must reference Azure" "$ARTIFACT_ROOT/artifacts/hld.md"
record_step "HLD markdown" "pass" "artifacts/hld.md ($(wc -c < "$ARTIFACT_ROOT/artifacts/hld.md") bytes)"

HLD_DOCX_JSON="$ARTIFACT_ROOT/raw/07-hld-docx.json"
request "hld-docx" POST "${API_BASE}/diagrams/${DIAGRAM_ID}/export-hld?format=docx&include_diagrams=true&export_mode=customer" "$HLD_DOCX_JSON" '{}'
validate_json_field "hld-docx" "$HLD_DOCX_JSON" '.content_b64 | type == "string" and length > 100' "HLD DOCX export must include content_b64"
python3 - "$HLD_DOCX_JSON" "$ARTIFACT_ROOT/artifacts/hld.docx" <<'PY'
import base64
import json
import sys

with open(sys.argv[1], encoding='utf-8') as handle:
  payload = json.load(handle)
with open(sys.argv[2], 'wb') as handle:
  handle.write(base64.b64decode(payload['content_b64']))
PY
if [[ $(wc -c < "$ARTIFACT_ROOT/artifacts/hld.docx") -lt 1000 ]]; then
  fail "hld-docx" "Decoded DOCX is unexpectedly small" "$HLD_DOCX_JSON"
fi
record_step "HLD DOCX" "pass" "artifacts/hld.docx ($(wc -c < "$ARTIFACT_ROOT/artifacts/hld.docx") bytes)"

COST_JSON="$ARTIFACT_ROOT/raw/08-cost.json"
request "cost" GET "${API_BASE}/diagrams/${DIAGRAM_ID}/cost-estimate" "$COST_JSON"
validate_json_field "cost" "$COST_JSON" '.currency == "USD"' "Cost estimate must include USD currency"
validate_json_field "cost" "$COST_JSON" '(.services // []) | length > 0' "Cost estimate must include service rows"
record_step "Cost estimate" "pass" "services=$(jq -r '(.services // []) | length' "$COST_JSON"), total=$(jq -rc '.total_monthly_estimate' "$COST_JSON")"

COST_CSV="$ARTIFACT_ROOT/artifacts/cost-estimate.csv"
request "cost-csv" GET "${API_BASE}/diagrams/${DIAGRAM_ID}/cost-estimate/export" "$COST_CSV"
grep -q '^Service,' "$COST_CSV" || fail "cost-csv" "Cost CSV missing header" "$COST_CSV"
grep -q '^TOTAL,' "$COST_CSV" || fail "cost-csv" "Cost CSV missing TOTAL row" "$COST_CSV"
record_step "Cost CSV" "pass" "artifacts/cost-estimate.csv ($(wc -l < "$COST_CSV") rows)"

PACKAGE_HTML_JSON="$ARTIFACT_ROOT/raw/09-architecture-package-html.json"
request "architecture-package-html" POST "${API_BASE}/diagrams/${DIAGRAM_ID}/export-architecture-package?format=html" "$PACKAGE_HTML_JSON" '{}'
write_content_artifact "$PACKAGE_HTML_JSON" '.content' "$ARTIFACT_ROOT/artifacts/architecture-package.html"
for expected_text in 'A — Target Azure Topology' 'B — DR Topology' 'Customer Intent' 'Assumptions And Constraints' '<svg'; do
  grep -q "$expected_text" "$ARTIFACT_ROOT/artifacts/architecture-package.html" || fail "architecture-package-html" "HTML package missing ${expected_text}" "$ARTIFACT_ROOT/artifacts/architecture-package.html"
done
record_step "Architecture Package HTML" "pass" "artifacts/architecture-package.html ($(wc -c < "$ARTIFACT_ROOT/artifacts/architecture-package.html") bytes)"

TARGET_SVG_JSON="$ARTIFACT_ROOT/raw/10-target-svg.json"
request "target-svg" POST "${API_BASE}/diagrams/${DIAGRAM_ID}/export-architecture-package?format=svg&diagram=primary" "$TARGET_SVG_JSON" '{}'
write_content_artifact "$TARGET_SVG_JSON" '.content' "$ARTIFACT_ROOT/artifacts/target.svg"
validate_svg "target-svg" "$ARTIFACT_ROOT/artifacts/target.svg" "Target"
record_step "Target SVG" "pass" "artifacts/target.svg ($(wc -c < "$ARTIFACT_ROOT/artifacts/target.svg") bytes)"

DR_SVG_JSON="$ARTIFACT_ROOT/raw/11-dr-svg.json"
request "dr-svg" POST "${API_BASE}/diagrams/${DIAGRAM_ID}/export-architecture-package?format=svg&diagram=dr" "$DR_SVG_JSON" '{}'
write_content_artifact "$DR_SVG_JSON" '.content' "$ARTIFACT_ROOT/artifacts/dr.svg"
validate_svg "dr-svg" "$ARTIFACT_ROOT/artifacts/dr.svg" "DR"
grep -Eqi 'replication|resilience|secondary|region' "$ARTIFACT_ROOT/artifacts/dr.svg" || fail "dr-svg" "DR SVG missing resilience/region language" "$ARTIFACT_ROOT/artifacts/dr.svg"
record_step "DR SVG" "pass" "artifacts/dr.svg ($(wc -c < "$ARTIFACT_ROOT/artifacts/dr.svg") bytes)"

CLASSIC_JSON="$ARTIFACT_ROOT/raw/12-classic-excalidraw.json"
request "classic-excalidraw" POST "${API_BASE}/diagrams/${DIAGRAM_ID}/export-diagram?format=excalidraw" "$CLASSIC_JSON" '{}'
write_content_artifact "$CLASSIC_JSON" '.content' "$ARTIFACT_ROOT/artifacts/classic.excalidraw"
python3 - "$ARTIFACT_ROOT/artifacts/classic.excalidraw" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as handle:
    payload = json.load(handle)
elements = payload.get('elements') if isinstance(payload, dict) else None
if not isinstance(elements, list) or not elements:
    raise SystemExit('classic Excalidraw export has no elements')
PY
record_step "Classic Excalidraw" "pass" "artifacts/classic.excalidraw ($(jq -r '.elements | length' "$ARTIFACT_ROOT/artifacts/classic.excalidraw") elements)"

if [[ "$SECONDARY_FORMAT_SMOKE" == "true" ]]; then
  IAC_BICEP_JSON="$ARTIFACT_ROOT/raw/13-iac-bicep.json"
  request "iac-bicep" POST "${API_BASE}/diagrams/${DIAGRAM_ID}/generate?format=bicep&force=true" "$IAC_BICEP_JSON" '{}'
  validate_json_field "iac-bicep" "$IAC_BICEP_JSON" '.code | type == "string" and length > 80' "Bicep response must include non-empty code"
  write_content_artifact "$IAC_BICEP_JSON" '.code' "$ARTIFACT_ROOT/artifacts/archmorph-iac.bicep"
  grep -Eq '^(targetScope|param |resource )' "$ARTIFACT_ROOT/artifacts/archmorph-iac.bicep" || fail "iac-bicep" "Bicep output lacks targetScope/param/resource content" "$ARTIFACT_ROOT/artifacts/archmorph-iac.bicep"
  ! grep -q '```' "$ARTIFACT_ROOT/artifacts/archmorph-iac.bicep" || fail "iac-bicep" "Bicep output contains markdown fences" "$ARTIFACT_ROOT/artifacts/archmorph-iac.bicep"
  record_step "IaC Bicep" "pass" "artifacts/archmorph-iac.bicep ($(wc -c < "$ARTIFACT_ROOT/artifacts/archmorph-iac.bicep") bytes)"

  IAC_CFN_JSON="$ARTIFACT_ROOT/raw/14-iac-cloudformation.json"
  request "iac-cloudformation" POST "${API_BASE}/diagrams/${DIAGRAM_ID}/generate?format=cloudformation&force=true" "$IAC_CFN_JSON" '{}'
  validate_json_field "iac-cloudformation" "$IAC_CFN_JSON" '.code | type == "string" and length > 80' "CloudFormation response must include non-empty code"
  write_content_artifact "$IAC_CFN_JSON" '.code' "$ARTIFACT_ROOT/artifacts/archmorph-iac.yaml"
  grep -Eq '^(AWSTemplateFormatVersion:|Resources:)' "$ARTIFACT_ROOT/artifacts/archmorph-iac.yaml" || fail "iac-cloudformation" "CloudFormation output lacks template/resource content" "$ARTIFACT_ROOT/artifacts/archmorph-iac.yaml"
  ! grep -q '```' "$ARTIFACT_ROOT/artifacts/archmorph-iac.yaml" || fail "iac-cloudformation" "CloudFormation output contains markdown fences" "$ARTIFACT_ROOT/artifacts/archmorph-iac.yaml"
  record_step "IaC CloudFormation" "pass" "artifacts/archmorph-iac.yaml ($(wc -c < "$ARTIFACT_ROOT/artifacts/archmorph-iac.yaml") bytes)"

  HLD_PDF_JSON="$ARTIFACT_ROOT/raw/15-hld-pdf.json"
  request "hld-pdf" POST "${API_BASE}/diagrams/${DIAGRAM_ID}/export-hld?format=pdf&include_diagrams=true&export_mode=customer" "$HLD_PDF_JSON" '{}'
  validate_json_field "hld-pdf" "$HLD_PDF_JSON" '.content_b64 | type == "string" and length > 100' "HLD PDF export must include content_b64"
  decode_base64_artifact "hld-pdf" "$HLD_PDF_JSON" "$ARTIFACT_ROOT/artifacts/hld.pdf" "%PDF" 1000
  record_step "HLD PDF" "pass" "artifacts/hld.pdf ($(wc -c < "$ARTIFACT_ROOT/artifacts/hld.pdf") bytes)"

  HLD_PPTX_JSON="$ARTIFACT_ROOT/raw/16-hld-pptx.json"
  request "hld-pptx" POST "${API_BASE}/diagrams/${DIAGRAM_ID}/export-hld?format=pptx&include_diagrams=true&export_mode=customer" "$HLD_PPTX_JSON" '{}'
  validate_json_field "hld-pptx" "$HLD_PPTX_JSON" '.content_b64 | type == "string" and length > 100' "HLD PPTX export must include content_b64"
  decode_base64_artifact "hld-pptx" "$HLD_PPTX_JSON" "$ARTIFACT_ROOT/artifacts/hld.pptx" "PK" 1000
  record_step "HLD PPTX" "pass" "artifacts/hld.pptx ($(wc -c < "$ARTIFACT_ROOT/artifacts/hld.pptx") bytes)"

  DRAWIO_JSON="$ARTIFACT_ROOT/raw/17-classic-drawio.json"
  request "classic-drawio" POST "${API_BASE}/diagrams/${DIAGRAM_ID}/export-diagram?format=drawio" "$DRAWIO_JSON" '{}'
  write_content_artifact "$DRAWIO_JSON" '.content' "$ARTIFACT_ROOT/artifacts/classic.drawio"
  validate_drawio "$ARTIFACT_ROOT/artifacts/classic.drawio" || fail "classic-drawio" "Draw.io XML validation failed" "$ARTIFACT_ROOT/artifacts/classic.drawio"
  record_step "Classic Draw.io" "pass" "artifacts/classic.drawio ($(wc -c < "$ARTIFACT_ROOT/artifacts/classic.drawio") bytes)"

  VDX_JSON="$ARTIFACT_ROOT/raw/18-classic-vdx.json"
  request "classic-vdx" POST "${API_BASE}/diagrams/${DIAGRAM_ID}/export-diagram?format=vsdx" "$VDX_JSON" '{}'
  write_content_artifact "$VDX_JSON" '.content' "$ARTIFACT_ROOT/artifacts/classic.vdx"
  validate_vdx "$ARTIFACT_ROOT/artifacts/classic.vdx" || fail "classic-vdx" "VDX XML validation failed" "$ARTIFACT_ROOT/artifacts/classic.vdx"
  record_step "Classic VDX" "pass" "artifacts/classic.vdx ($(wc -c < "$ARTIFACT_ROOT/artifacts/classic.vdx") bytes)"
else
  record_step "Secondary artifact formats" "skip" "SECONDARY_FORMAT_SMOKE=false"
fi

jq -nc \
  --arg api_base "$API_BASE" \
  --arg frontend_url "${FRONTEND_URL:-}" \
  --arg sample_id "$SAMPLE_ID" \
  --arg diagram_id "$DIAGRAM_ID" \
  --arg commit_sha "$COMMIT_SHA" \
  --arg run_id "$RUN_ID" \
  --arg artifact_root "$ARTIFACT_ROOT" \
  '{api_base:$api_base, frontend_url:$frontend_url, sample_id:$sample_id, diagram_id:$diagram_id, commit_sha:$commit_sha, run_id:$run_id, artifact_root:$artifact_root, status:"passed"}' > "$ARTIFACT_ROOT/manifest.json"

for artifact_path in "$ARTIFACT_ROOT"/artifacts/*; do
  [[ -f "$artifact_path" ]] || continue
  jq -nc --arg path "$artifact_path" --arg bytes "$(wc -c < "$artifact_path")" '{path:$path, bytes:($bytes|tonumber)}' >> "$MANIFEST"
done

echo "" >> "$SUMMARY"
echo "Smoke passed. Artifact root: \`${ARTIFACT_ROOT}\`" >> "$SUMMARY"
echo "Architecture Package production smoke passed."