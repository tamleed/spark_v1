#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"
API_KEY="${GATEWAY_API_KEY:-${API_KEY:-}}"
MODEL_A="${MODEL_A:-gpt-oss20b}"
MODEL_B="${MODEL_B:-qwen3}"
JOB_TIMEOUT_SEC="${JOB_TIMEOUT_SEC:-240}"
POLL_SEC="${POLL_SEC:-2}"

if [ -z "${API_KEY}" ]; then
  echo "[ERR] Set GATEWAY_API_KEY or API_KEY" >&2
  exit 1
fi

available_models="$(curl -fsS -H "X-API-Key: ${API_KEY}" "${API_URL}/v1/models")"
echo "${available_models}" | jq -e --arg m "${MODEL_A}" '.data[]? | select(.id == $m)' >/dev/null || {
  echo "[ERR] MODEL_A '${MODEL_A}' not found in /v1/models" >&2
  echo "${available_models}" | jq -r '.data[].id' >&2
  exit 1
}
echo "${available_models}" | jq -e --arg m "${MODEL_B}" '.data[]? | select(.id == $m)' >/dev/null || {
  echo "[ERR] MODEL_B '${MODEL_B}' not found in /v1/models" >&2
  echo "${available_models}" | jq -r '.data[].id' >&2
  exit 1
}

submit_job() {
  local model="$1"
  local prompt="$2"
  curl -fsS -X POST "${API_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d "{
      \"model\":\"${model}\",
      \"messages\":[{\"role\":\"user\",\"content\":\"${prompt}\"}],
      \"stream\":false,
      \"async\":true
    }" | jq -r '.job_id'
}

wait_job() {
  local job_id="$1"
  local timeout_sec="$2"
  local deadline=$((SECONDS + timeout_sec))
  while [ "$SECONDS" -lt "$deadline" ]; do
    local meta status
    meta="$(curl -fsS -H "X-API-Key: ${API_KEY}" "${API_URL}/jobs/${job_id}")"
    status="$(echo "${meta}" | jq -r '.status')"
    if [ "${status}" = "succeeded" ]; then
      return 0
    fi
    if [ "${status}" = "failed" ] || [ "${status}" = "not_completed" ] || [ "${status}" = "cancelled" ]; then
      echo "[ERR] job ${job_id} failed with status=${status}" >&2
      echo "${meta}" >&2
      return 1
    fi
    sleep "${POLL_SEC}"
  done
  echo "[ERR] timeout waiting for ${job_id} (${timeout_sec}s)" >&2
  return 1
}

job_a="$(submit_job "${MODEL_A}" "Ответь одним словом: ok")"
echo "[INFO] ${MODEL_A} job=${job_a}"
wait_job "${job_a}" "${JOB_TIMEOUT_SEC}"
echo "[OK] ${MODEL_A} responded"
curl -fsS -H "X-API-Key: ${API_KEY}" "${API_URL}/jobs/${job_a}/result" | jq

job_b="$(submit_job "${MODEL_B}" "Ответь одним словом: ok")"
echo "[INFO] ${MODEL_B} job=${job_b}"
wait_job "${job_b}" "${JOB_TIMEOUT_SEC}"
echo "[OK] ${MODEL_B} responded"
curl -fsS -H "X-API-Key: ${API_KEY}" "${API_URL}/jobs/${job_b}/result" | jq

echo "[OK] both models are reachable via async jobs"
