#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"
API_KEY="${GATEWAY_API_KEY:-${API_KEY:-}}"
DISCOVERY_ROOT="${DISCOVERY_ROOT:-/opt/llm-switchboard/models}"
TEST_MODEL="${TEST_MODEL:-codex-hot-discovery-$(date +%s)}"

if [ -z "${API_KEY}" ]; then
  echo "[ERR] Set GATEWAY_API_KEY or API_KEY" >&2
  exit 1
fi

before="$(curl -fsS -H "X-API-Key: ${API_KEY}" "${API_URL}/v1/models")"
echo "$before" | jq -e --arg model "$TEST_MODEL" '.data[]? | select(.id == $model)' >/dev/null && {
  echo "[ERR] test model already present before creation" >&2
  exit 1
}

mkdir -p "${DISCOVERY_ROOT}/${TEST_MODEL}"
cleanup() {
  rmdir "${DISCOVERY_ROOT}/${TEST_MODEL}" 2>/dev/null || true
}
trap cleanup EXIT

after="$(curl -fsS -H "X-API-Key: ${API_KEY}" "${API_URL}/v1/models")"
echo "$after" | jq -e --arg model "$TEST_MODEL" '.data[]? | select(.id == $model)' >/dev/null

echo "[OK] hot model discovery works for ${TEST_MODEL}"
