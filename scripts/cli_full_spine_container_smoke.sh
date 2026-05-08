#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="${ARCHMORPH_SMOKE_IMAGE:-archmorph-backend-cli-smoke}"
CONTAINER_NAME="${ARCHMORPH_SMOKE_CONTAINER:-archmorph-cli-smoke-$$}"
PORT="${ARCHMORPH_SMOKE_PORT:-18080}"
WORK_DIR="${ARCHMORPH_SMOKE_WORK_DIR:-$(mktemp -d)}"
OUT_DIR="$WORK_DIR/out"
DIAGRAM_PATH="$WORK_DIR/aws.png"
API_URL="http://127.0.0.1:$PORT"
BOOTSTRAP_PYTHON="${PYTHON:-}"
VENV_DIR="$WORK_DIR/.venv"
TOKEN_PATH="$WORK_DIR/session.token"

if [[ -z "$BOOTSTRAP_PYTHON" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    BOOTSTRAP_PYTHON="python3"
  elif command -v python >/dev/null 2>&1; then
    BOOTSTRAP_PYTHON="python"
  else
    echo "python3 or python is required" >&2
    exit 1
  fi
fi

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  if [[ -z "${ARCHMORPH_SMOKE_WORK_DIR:-}" ]]; then
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT

"$BOOTSTRAP_PYTHON" -m venv "$VENV_DIR"
PYTHON_BIN="$VENV_DIR/bin/python"
"$PYTHON_BIN" -m pip install --upgrade pip >/dev/null
"$PYTHON_BIN" -m pip install -e "$ROOT_DIR/cli" >/dev/null

docker build -t "$IMAGE_NAME" "$ROOT_DIR/backend" >/dev/null

docker run -d \
  --name "$CONTAINER_NAME" \
  -p "127.0.0.1:$PORT:8000" \
  -e ENVIRONMENT=test \
  -e RATE_LIMIT_ENABLED=false \
  -e ARCHMORPH_CI_SMOKE_MODE=1 \
  -e ARCHMORPH_EXPORT_CAPABILITY_REQUIRED=false \
  -e ARCHMORPH_DISABLE_IAC_CLI_VALIDATION=1 \
  -e DATABASE_URL=sqlite:///./data/archmorph-smoke.db \
  "$IMAGE_NAME" \
  uvicorn main:app --host 0.0.0.0 --port 8000 >/dev/null

"$PYTHON_BIN" - <<PY
import sys
import time
import urllib.request

url = "$API_URL/api/health"
for _ in range(90):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            if response.status == 200:
                sys.exit(0)
    except Exception:
        time.sleep(1)
print("backend container did not become healthy", file=sys.stderr)
sys.exit(1)
PY

mkdir -p "$OUT_DIR"
"$PYTHON_BIN" - <<PY
from pathlib import Path
Path("$DIAGRAM_PATH").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 100)
PY

"$PYTHON_BIN" - <<PY > "$TOKEN_PATH"
import base64
import hashlib
import hmac
import json
import os
import time


def _b64url(data: bytes) -> str:
  return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


secret = os.getenv("JWT_SECRET") or "archmorph-dev-secret-change-in-production"
header = {"alg": "HS256", "typ": "JWT"}
payload = {
  "sub": "cli-container-smoke-user",
  "email": "cli-container-smoke@example.com",
  "name": "CLI Container Smoke",
  "avatar_url": None,
  "provider": "github",
  "tier": "team",
  "tenant_id": "tenant-cli-container-smoke",
  "roles": ["user"],
  "iat": int(time.time()),
  "exp": int(time.time()) + 3600,
  "type": "access",
}
signing_input = ".".join(
  _b64url(json.dumps(part, separators=(",", ":")).encode("utf-8"))
  for part in (header, payload)
)
signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
print(f"{signing_input}.{_b64url(signature)}")
PY

"$PYTHON_BIN" -m archmorph_cli --api-url "$API_URL" --token "$(cat "$TOKEN_PATH")" run \
  --diagram "$DIAGRAM_PATH" \
  --target-rg rg-cli-smoke-dev \
  --emit terraform,bicep,alz-svg,cost \
  --out "$OUT_DIR"

"$PYTHON_BIN" - <<PY
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

out = Path("$OUT_DIR")
required = [
    out / "analysis.json",
    out / "terraform" / "main.tf",
    out / "bicep" / "main.bicep",
    out / "alz.svg",
    out / "cost-estimate.json",
    out / "run-summary.json",
]
missing = [str(path) for path in required if not path.exists()]
if missing:
    print("Missing artifacts: " + ", ".join(missing), file=sys.stderr)
    sys.exit(1)

analysis = json.loads((out / "analysis.json").read_text(encoding="utf-8"))
assert analysis["diagram_id"].startswith("diag-"), analysis["diagram_id"]
assert analysis["cli_run"]["target_resource_group"] == "rg-cli-smoke-dev"
assert analysis["services_detected"] >= 3

terraform = (out / "terraform" / "main.tf").read_text(encoding="utf-8")
bicep = (out / "bicep" / "main.bicep").read_text(encoding="utf-8")
assert 'resource "terraform_data"' in terraform
assert "Microsoft.Resources/resourceGroups" in bicep
ET.fromstring((out / "alz.svg").read_text(encoding="utf-8"))

cost = json.loads((out / "cost-estimate.json").read_text(encoding="utf-8"))
assert cost["currency"] == "USD"
summary = json.loads((out / "run-summary.json").read_text(encoding="utf-8"))
assert summary["artifacts"]["analysis"].endswith("analysis.json")
print("CLI container smoke artifacts validated:", out)
PY
