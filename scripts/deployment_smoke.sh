#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-}"
FRONTEND_URL="${FRONTEND_URL:-}"

if [[ -z "$API_URL" ]]; then
  echo "::error::API_URL is required"
  exit 1
fi

if [[ -z "$FRONTEND_URL" ]]; then
  echo "::error::FRONTEND_URL is required"
  exit 1
fi

API_URL="${API_URL%/}"
FRONTEND_URL="${FRONTEND_URL%/}"
API_ROOT="${API_URL%/api}"
HEALTH_API_KEY="${HEALTH_API_KEY:-${ARCHMORPH_API_KEY:-${ADMIN_KEY:-}}}"

check_status() {
  local label="$1"
  local url="$2"
  local expected_pattern="${3:-^(200|301|302|307|308)$}"
  local status

  status=$(curl -sS -o /tmp/archmorph-smoke-body -w "%{http_code}" --max-time 30 "$url")
  if [[ ! "$status" =~ $expected_pattern ]]; then
    echo "::error::$label returned HTTP $status for $url"
    head -c 500 /tmp/archmorph-smoke-body || true
    echo
    exit 1
  fi
  echo "$label OK ($status)"
}

check_status "Frontend root" "$FRONTEND_URL"
check_status "Frontend translator route" "$FRONTEND_URL/#translator"

HEALTH_RETRIES=3 HEALTH_RETRY_SECONDS=10 HEALTH_API_KEY="$HEALTH_API_KEY" "$(dirname "$0")/health_gate.sh" "$API_URL/health"

OPENAPI_STATUS=$(curl -sS -o /tmp/archmorph-openapi -w "%{http_code}" --max-time 30 "$API_ROOT/openapi.json")
if [[ "$OPENAPI_STATUS" != "200" ]]; then
  echo "::error::OpenAPI schema returned HTTP $OPENAPI_STATUS"
  head -c 500 /tmp/archmorph-openapi || true
  echo
  exit 1
fi

OPENAPI_TITLE=$(jq -r '.info.title // ""' /tmp/archmorph-openapi)
if [[ "$OPENAPI_TITLE" != "Archmorph API" ]]; then
  echo "::error::Unexpected OpenAPI title: $OPENAPI_TITLE"
  exit 1
fi
echo "OpenAPI schema OK ($OPENAPI_TITLE)"

echo "Deployment smoke checks passed."
