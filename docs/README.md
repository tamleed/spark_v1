# LLM Switchboard for NVIDIA DGX Spark

> Russian version: `docs/README_RUS.md`.

## Architecture
- `gateway` is the HTTP/API entrypoint. It validates keys, exposes `/v1/chat/completions`, `/jobs/*`, `/status`, and `/queue`.
- `worker` is a **containerized orchestrator**. It consumes RQ jobs from Redis, performs model switching, and launches/stops backend vLLM containers through the host Docker daemon.
- `ModelSwitcher` stops the previous backend container, starts a new vLLM backend container with GPU access, waits for `/v1/models` readiness, and only then proxies inference.
- `redis` stores queue state and job metadata.

## DGX Spark deployment notes
- DGX Spark is an ARM64 / Blackwell platform. This project assumes you provide a **Spark-compatible** vLLM backend image.
- The backend image is selected in this order:
  1. `backend.image` for a model in `configs/models.yaml`
  2. `VLLM_IMAGE`
  3. `inference_backend.default_image` in `configs/gateway.yaml`
- The default image in this repo is `nvcr.io/nvidia/vllm:26.02-py3`, but you should validate the tag for your Spark software stack and override it if needed.
- The worker container needs:
  - Docker CLI inside the image,
  - `/var/run/docker.sock` mounted from the host,
  - host model directories mounted for discovery/orchestration.

## Quick deploy
```bash
sudo mkdir -p /opt/llm-switchboard
sudo rsync -a ./ /opt/llm-switchboard/
cd /opt/llm-switchboard

./scripts/install_prereqs.sh
sudo cp .env.example /etc/llm-gateway.env
sudo nano /etc/llm-gateway.env

./scripts/pull_vllm_image.sh    # prefetch only
./scripts/start_all.sh
```

## Required environment
`/etc/llm-gateway.env`
```env
GATEWAY_API_KEY=<primary_key>
ADMIN_API_KEY=<admin_key>
HF_TOKEN=
REDIS_URL=redis://127.0.0.1:6379/0
MODELS_YAML_PATH=/opt/llm-switchboard/configs/models.yaml
GATEWAY_YAML_PATH=/opt/llm-switchboard/configs/gateway.yaml
MODEL_DISCOVERY_DIRS=/opt/llm-switchboard/models:/opt/llm-switchboard/model:/mnt/models
VLLM_IMAGE=nvcr.io/nvidia/vllm:26.02-py3
DOCKER_BIN=/usr/bin/docker
DOCKER_RUNTIME=nvidia
DOCKER_NETWORK_MODE=host
DOCKER_IPC_MODE=host
DOCKER_SHM_SIZE=16g
```

## Compose/runtime behavior
- `docker compose up -d` starts `redis`, `gateway`, and `worker`.
- `worker` runs as `python -m worker.worker` and has Docker socket access.
- `gateway` and `worker` both use `PYTHONPATH=/app:/app/gateway` for package imports.
- `pull_vllm_image.sh` is a prefetch helper only; actual backend selection still comes from model config/env at runtime.

## Model switching flow
1. Client calls `POST /v1/chat/completions`.
2. Gateway enqueues `worker.tasks.execute_chat_job`.
3. Worker marks the job `running`, calls `ensure_model_active()`, and resolves the target model.
4. `ModelSwitcher` stops the previous backend container, launches the new vLLM backend container with GPU flags, and polls `http://127.0.0.1:<port>/v1/models`.
5. Once ready, worker proxies chat completion to the backend.

## Readiness / validation commands
### Base services
```bash
cd /opt/llm-switchboard/docker
docker compose ps
curl -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/health
```

### Worker runtime checks
```bash
./scripts/check_worker_runtime.sh
```
This verifies:
- `docker ps` works inside `worker`,
- `import worker.tasks` works,
- `from gateway.app.config import load_config` works.

### GPU visibility
```bash
cd /opt/llm-switchboard/docker
docker compose --profile dgx-check up dgx-gpu-check
```

### Model registry and switching
```bash
curl -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/v1/models
curl -H "X-API-Key: $ADMIN_API_KEY" http://127.0.0.1:8000/status
curl -H "X-API-Key: $ADMIN_API_KEY" http://127.0.0.1:8000/queue
```

### End-to-end smoke test
```bash
API_URL=http://127.0.0.1:8000 \
GATEWAY_API_KEY='<key>' \
./scripts/smoke_test.sh
```
The smoke test exercises queueing, completion polling, and cancel. Note that your configured model names must match the script's expectations or you should adapt the script for your deployment.

## Troubleshooting
### `module 'worker' has no attribute 'tasks'`
- Ensure `worker/__init__.py` exists and the worker service runs as `python -m worker.worker`.

### `FileNotFoundError: 'docker'`
- Worker image must contain Docker CLI and the worker service must mount `/var/run/docker.sock`.

### Backend never becomes ready
- Inspect worker logs and backend container logs:
```bash
cd /opt/llm-switchboard/docker
docker compose logs --tail=200 worker
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
docker logs --tail=200 llm-backend-<model-name>
```

### Auto-discovery does not find host model directories
- `gateway` and `worker` discover models from mounted directories. Keep your models in `/mnt/models`, `/opt/llm-switchboard/models`, or `/opt/llm-switchboard/model`, or mount additional host directories consistently.
