#!/usr/bin/env bash
set -euo pipefail
cd /opt/llm-switchboard/docker

docker compose up -d redis gateway worker

echo "[OK] started containers: redis/gateway/worker"
