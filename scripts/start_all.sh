#!/usr/bin/env bash
set -euo pipefail
cd /opt/llm-switchboard/docker

docker compose up -d redis gateway worker

sudo cp /opt/llm-switchboard/systemd/jupyter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now jupyter.service

echo "[OK] started containers: redis/gateway/worker + systemd jupyter"
