#!/usr/bin/env bash
set -euo pipefail
cd /opt/llm-switchboard/docker

docker compose exec -T worker docker ps >/dev/null

docker compose exec -T worker python -c "import worker.tasks; print(worker.tasks.execute_chat_job)" >/dev/null

docker compose exec -T worker python -c "from gateway.app.config import load_config; print(load_config)" >/dev/null

echo "[OK] worker runtime can access docker and import project packages"
