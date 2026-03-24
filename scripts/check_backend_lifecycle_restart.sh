#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"
API_KEY="${GATEWAY_API_KEY:-${API_KEY:-}}"
MODEL="${MODEL:-}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/llm-switchboard/docker}"

if [ -z "${API_KEY}" ]; then
  echo "[ERR] Set GATEWAY_API_KEY or API_KEY" >&2
  exit 1
fi

if [ -z "${MODEL}" ]; then
  MODEL="$(curl -fsS -H "X-API-Key: ${API_KEY}" "${API_URL}/v1/models" | jq -r '.data[0].id')"
fi

if [ -z "${MODEL}" ] || [ "${MODEL}" = "null" ]; then
  echo "[ERR] Could not resolve model id from /v1/models" >&2
  exit 1
fi

submit_job() {
  local model="$1"
  curl -fsS -X POST "${API_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d "{
      \"model\":\"${model}\",
      \"messages\":[{\"role\":\"user\",\"content\":\"say ok\"}],
      \"stream\":false,
      \"async\":true
    }" | jq -r '.job_id'
}

wait_job() {
  local job_id="$1"
  local timeout_sec="${2:-300}"
  local deadline=$((SECONDS + timeout_sec))
  while [ "$SECONDS" -lt "$deadline" ]; do
    local meta
    meta="$(curl -fsS -H "X-API-Key: ${API_KEY}" "${API_URL}/jobs/${job_id}")"
    local status
    status="$(echo "$meta" | jq -r '.status')"
    if [ "${status}" = "succeeded" ]; then
      return 0
    fi
    if [ "${status}" = "failed" ] || [ "${status}" = "not_completed" ] || [ "${status}" = "cancelled" ]; then
      echo "[ERR] job ${job_id} finished with status=${status}" >&2
      echo "$meta" >&2
      return 1
    fi
    sleep 2
  done
  echo "[ERR] timeout waiting for job ${job_id}" >&2
  return 1
}

echo "[INFO] using model: ${MODEL}"

job1="$(submit_job "${MODEL}")"
echo "[INFO] job1=${job1}"
wait_job "${job1}" 600

echo "[INFO] restarting gateway/worker..."
(
  cd "${COMPOSE_DIR}"
  docker compose restart gateway worker
)

for _ in $(seq 1 60); do
  if curl -fsS -H "X-API-Key: ${API_KEY}" "${API_URL}/health" >/dev/null; then
    break
  fi
  sleep 2
done

job2="$(submit_job "${MODEL}")"
echo "[INFO] job2=${job2}"
wait_job "${job2}" 600

echo "[OK] backend lifecycle survives gateway/worker restart without container name conflicts"
