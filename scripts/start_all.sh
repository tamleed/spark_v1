#!/usr/bin/env bash
set -euo pipefail
cd /opt/llm-switchboard/docker
docker compose up -d redis
sudo cp /opt/llm-switchboard/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now llm-gateway.service
sudo systemctl enable --now llm-worker.service
sudo systemctl enable --now jupyter.service
echo "[OK] all services started"
