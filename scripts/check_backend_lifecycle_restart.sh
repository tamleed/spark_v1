#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"
API_KEY="${GATEWAY_API_KEY:-${API_KEY:-}}"
MODEL="${MODEL:-}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/llm-switchboard/docker}"
JOB_TIMEOUT_SEC="${JOB_TIMEOUT_SEC:-240}"
POLL_SEC="${POLL_SEC:-2}"

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
  local timeout_sec="${2:-${JOB_TIMEOUT_SEC}}"
  local deadline=$((SECONDS + timeout_sec))
  local last_status=""
  local poll_count=0
  while [ "$SECONDS" -lt "$deadline" ]; do
    local meta
    meta="$(curl -fsS -H "X-API-Key: ${API_KEY}" "${API_URL}/jobs/${job_id}")"
    local status
    status="$(echo "$meta" | jq -r '.status')"
    if [ "${status}" != "${last_status}" ]; then
      echo "[INFO] job ${job_id} status=${status}"
      last_status="${status}"
    fi
    if [ "${status}" = "succeeded" ]; then
      return 0
    fi
    if [ "${status}" = "failed" ] || [ "${status}" = "not_completed" ] || [ "${status}" = "cancelled" ]; then
      echo "[ERR] job ${job_id} finished with status=${status}" >&2
      echo "$meta" >&2
      return 1
    fi
    poll_count=$((poll_count + 1))
    if [ $((poll_count % 15)) -eq 0 ]; then
      echo "[INFO] still waiting for ${job_id} ..."
    fi
    sleep "${POLL_SEC}"
  done
  echo "[ERR] timeout waiting for job ${job_id} (${timeout_sec}s). Try a smaller model or increase JOB_TIMEOUT_SEC." >&2
  return 1
}

echo "[INFO] using model: ${MODEL}"

job1="$(submit_job "${MODEL}")"
echo "[INFO] job1=${job1}"
wait_job "${job1}" "${JOB_TIMEOUT_SEC}"

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
wait_job "${job2}" "${JOB_TIMEOUT_SEC}"

echo "[OK] backend lifecycle survives gateway/worker restart without container name conflicts"
