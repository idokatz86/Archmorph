#!/usr/bin/env bash
set -euo pipefail

HEALTH_URL="${1:-${HEALTH_URL:-}}"
HEALTH_BODY="${HEALTH_BODY:-}"
HEALTH_RETRIES="${HEALTH_RETRIES:-3}"
HEALTH_RETRY_SECONDS="${HEALTH_RETRY_SECONDS:-10}"

if [[ -z "$HEALTH_URL" && -z "$HEALTH_BODY" ]]; then
  echo "::error::health gate requires a URL argument, HEALTH_URL, or HEALTH_BODY"
  exit 1
fi

fetch_health() {
  if [[ -n "$HEALTH_BODY" ]]; then
    printf '%s' "$HEALTH_BODY"
    return 0
  fi

  curl -sS --max-time 30 "$HEALTH_URL"
}

health_json=""
for attempt in $(seq 1 "$HEALTH_RETRIES"); do
  if health_json="$(fetch_health)"; then
    status="$(printf '%s' "$health_json" | jq -r '.status // "unknown"' 2>/dev/null || echo failed)"
    if [[ "$status" == "healthy" ]]; then
      break
    fi
  else
    status="failed"
  fi

  if [[ "$attempt" -lt "$HEALTH_RETRIES" ]]; then
    echo "Health gate attempt $attempt returned $status; retrying in ${HEALTH_RETRY_SECONDS}s..."
    sleep "$HEALTH_RETRY_SECONDS"
  fi
done

if [[ -z "$health_json" ]]; then
  echo "::error::Health gate could not retrieve a health response"
  exit 1
fi

status="$(printf '%s' "$health_json" | jq -r '.status // "unknown"' 2>/dev/null || echo failed)"
version="$(printf '%s' "$health_json" | jq -r '.version // "unknown"' 2>/dev/null || echo unknown)"

if [[ "$status" == "failed" || "$status" == "unknown" ]]; then
  echo "::error::Health gate could not parse a valid health JSON status after ${HEALTH_RETRIES} attempt(s)"
  printf '%s\n' "$health_json"
  exit 1
fi

if [[ "$status" != "healthy" ]]; then
  echo "::error::Production health gate requires status=healthy, got status=${status}"
  printf '%s' "$health_json" | jq -c '{status, version, checks, service_catalog_refresh, scheduled_jobs}' || printf '%s\n' "$health_json"
  exit 1
fi

if printf '%s' "$health_json" | jq -e '.service_catalog_refresh.stale == true' >/dev/null; then
  echo "::error::service_catalog_refresh is stale"
  printf '%s' "$health_json" | jq -c '.service_catalog_refresh'
  exit 1
fi

stale_jobs="$(printf '%s' "$health_json" | jq -r '[.scheduled_jobs[]? | select(.stale == true) | .name] | join(",")')"
if [[ -n "$stale_jobs" ]]; then
  echo "::error::Scheduled jobs are stale: ${stale_jobs}"
  printf '%s' "$health_json" | jq -c '[.scheduled_jobs[]? | select(.stale == true)]'
  exit 1
fi

redis_status="$(printf '%s' "$health_json" | jq -r '.checks.redis // empty')"
redis_scale_blocked="$(printf '%s' "$health_json" | jq -r '.checks.redis_readiness.scale_blocked // false')"
if [[ "$redis_status" == "missing_required" ]]; then
  echo "::error::Redis is required but not configured"
  printf '%s' "$health_json" | jq -c '.checks.redis_readiness // {redis: .checks.redis}'
  exit 1
elif [[ "$redis_scale_blocked" == "true" ]]; then
  echo "::error::Redis is required before horizontal scale"
  printf '%s' "$health_json" | jq -c '.checks.redis_readiness'
  exit 1
elif [[ "$redis_status" == "not_configured" || "$redis_status" == "disabled_optional" ]]; then
  echo "::warning::Redis is disabled as an optional dependency; accepted because overall production health is healthy"
fi

echo "Production health gate passed: status=${status} version=${version}"
