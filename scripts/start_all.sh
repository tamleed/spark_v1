#!/usr/bin/env bash
set -euo pipefail
cd /opt/llm-switchboard/docker

docker compose up -d redis gateway worker

if [ "${SKIP_PREFLIGHT:-0}" != "1" ]; then
  /opt/llm-switchboard/scripts/check_worker_runtime.sh
fi

API_KEY="${GATEWAY_API_KEY:-}"
if [ -n "${API_KEY}" ]; then
  for _ in $(seq 1 20); do
    if curl -fsS -H "X-API-Key: ${API_KEY}" http://127.0.0.1:8000/health >/dev/null 2>&1; then
      echo "[OK] gateway health endpoint is reachable"
      break
    fi
    sleep 1
  done
fi

echo "[OK] started containers: redis/gateway/worker"
