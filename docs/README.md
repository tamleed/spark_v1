# LLM Switchboard for NVIDIA DGX Spark

> Russian version: `docs/README_RUS.md`.

## Architecture
- `gateway` accepts API traffic and exposes `/v1/chat/completions`, `/jobs/*`, `/status`, and `/queue`.
- `worker` is a containerized orchestrator: it consumes RQ jobs from Redis, uses `ModelSwitcher` to stop the old backend container, start the next vLLM backend container, wait for readiness, and then proxy inference.
- `redis` stores queue state and job metadata.
- Backend model containers are **dynamic**. They are not permanent compose services; they are launched on-demand by the worker via host Docker.

## DGX Spark deployment notes
- DGX Spark is an ARM64 / Blackwell system. Use a Spark-compatible vLLM image/tag.
- Default backend image resolution order:
  1. `backend.image` in `configs/models.yaml`
  2. `VLLM_IMAGE`
  3. `inference_backend.default_image` in `configs/gateway.yaml`
- This repo defaults to `nvcr.io/nvidia/vllm:26.02-py3`. Validate this tag on your Spark software stack and override it if your environment requires a different NGC tag.
- The worker container needs:
  - Docker CLI inside the image,
  - `/var/run/docker.sock` mounted from the host,
  - mounted model directories for discovery,
  - host networking to talk to the backend container on `127.0.0.1:<port>`.

## Quick deploy
```bash
sudo mkdir -p /opt/llm-switchboard
sudo rsync -a ./ /opt/llm-switchboard/
cd /opt/llm-switchboard

./scripts/install_prereqs.sh
sudo cp .env.example /etc/llm-gateway.env
sudo nano /etc/llm-gateway.env

./scripts/pull_vllm_image.sh   # prefetch only
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
- `worker` runs as `python -m worker.worker`.
- `gateway` and `worker` both use `PYTHONPATH=/app:/app/gateway`.
- `gateway` and `worker` both mount the model discovery directories, so model discovery can update while the stack is already running.
- `pull_vllm_image.sh` is only a prefetch helper; runtime image choice still comes from model config/env.

## Model switching flow
1. Client calls `POST /v1/chat/completions`.
2. Gateway enqueues `worker.tasks.execute_chat_job`.
3. Worker marks the job `running`, resolves the model, and calls `ensure_model_active()`.
4. `ModelSwitcher` stops the previous backend container, starts the requested vLLM backend container with GPU flags, and polls `http://127.0.0.1:<port>/v1/models`.
5. Once ready, worker proxies inference to the backend and stores the result on the job.

## Hot model discovery without restarting the stack
Hot discovery works because `/v1/models` rebuilds the model list on every request and because the compose services now mount the host model directories.

### To add a model while the stack is already running
1. Copy the model directory into one of the discovery roots, for example:
```bash
mkdir -p /opt/llm-switchboard/models/my-new-model
# copy model files into /opt/llm-switchboard/models/my-new-model
```
2. Query the model list again:
```bash
curl -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/v1/models
```
3. The new directory name should appear as a model id without restarting `gateway` or `worker`.

### Automated hot-discovery check
```bash
API_URL=http://127.0.0.1:8000 \
GATEWAY_API_KEY='<key>' \
./scripts/check_hot_model_discovery.sh
```
The script creates a temporary model directory under `/opt/llm-switchboard/models`, calls `/v1/models` again, and verifies that the model becomes visible without restarting the stack.

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

## API test requests
### Local on the server
```bash
API_BASE="http://127.0.0.1:8000"
API_KEY="$GATEWAY_API_KEY"
ADMIN_KEY="$ADMIN_API_KEY"
```

#### Health
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/health"
```

#### Model list
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/v1/models"
```

#### Async chat completion
```bash
curl -X POST "$API_BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "model":"gpt-oss-20b",
    "messages":[{"role":"user","content":"Hello"}],
    "stream":false,
    "async":true
  }'
```

### Real scenario: ask one model, then another model
Below is a ready-to-run command sequence.

1) List available models and pick two `id` values:
```bash
curl -s -H "X-API-Key: $API_KEY" "$API_BASE/v1/models" | jq -r '.data[].id'
```

2) Ask the first question to model A (replace `MODEL_A`):
```bash
MODEL_A="gpt-oss-20b"
JOB1=$(curl -s -X POST "$API_BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d "{
    \"model\":\"$MODEL_A\",
    \"messages\":[{\"role\":\"user\",\"content\":\"Briefly explain what RAG is and when to use it.\"}],
    \"stream\":false,
    \"async\":true
  }" | jq -r '.job_id')
echo "JOB1=$JOB1"
```

3) Wait for job 1 and fetch its result:
```bash
until [[ "$(curl -s -H "X-API-Key: $API_KEY" "$API_BASE/jobs/$JOB1" | jq -r '.status')" == "succeeded" ]]; do
  echo "waiting for $JOB1..."
  sleep 2
done
curl -s -H "X-API-Key: $API_KEY" "$API_BASE/jobs/$JOB1/result" | jq
```

4) Ask the second question to model B (replace `MODEL_B`):
```bash
MODEL_B="qwen2.5-7b-instruct"
JOB2=$(curl -s -X POST "$API_BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d "{
    \"model\":\"$MODEL_B\",
    \"messages\":[{\"role\":\"user\",\"content\":\"Compare RAG vs fine-tuning in 5 bullet points.\"}],
    \"stream\":false,
    \"async\":true
  }" | jq -r '.job_id')
echo "JOB2=$JOB2"
```

5) Wait for job 2 and fetch its result:
```bash
until [[ "$(curl -s -H "X-API-Key: $API_KEY" "$API_BASE/jobs/$JOB2" | jq -r '.status')" == "succeeded" ]]; do
  echo "waiting for $JOB2..."
  sleep 2
done
curl -s -H "X-API-Key: $API_KEY" "$API_BASE/jobs/$JOB2/result" | jq
```

> Important: for different models, submit separate async jobs. The worker will switch backend containers between `MODEL_A` and `MODEL_B` automatically.

#### Job status/result
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>"
curl -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>/result"
```

#### Admin status/queue
```bash
curl -H "X-API-Key: $ADMIN_KEY" "$API_BASE/status"
curl -H "X-API-Key: $ADMIN_KEY" "$API_BASE/queue"
```

### From another computer via your domain name
Replace `api.example.com` with your actual published host name (for example a Tailscale Funnel domain or your own reverse-proxied domain).

```bash
API_BASE="https://api.example.com"
API_KEY="<gateway_key>"
ADMIN_KEY="<admin_key>"
```

#### Health
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/health"
```

#### Model list
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/v1/models"
```

#### Async chat completion
```bash
curl -X POST "$API_BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "model":"gpt-oss-20b",
    "messages":[{"role":"user","content":"Привет"}],
    "stream":false,
    "async":true
  }'
```

#### Job status/result
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>"
curl -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>/result"
```

#### Admin status/queue
```bash
curl -H "X-API-Key: $ADMIN_KEY" "$API_BASE/status"
curl -H "X-API-Key: $ADMIN_KEY" "$API_BASE/queue"
```

## End-to-end smoke test
```bash
API_URL=http://127.0.0.1:8000 \
GATEWAY_API_KEY='<key>' \
./scripts/smoke_test.sh
```
The smoke test exercises queueing, completion polling, and cancel. Adjust model names to match your deployment if needed.

## Troubleshooting
### `module 'worker' has no attribute 'tasks'`
- Ensure `worker/__init__.py` exists and the worker service runs as `python -m worker.worker`.

### `FileNotFoundError: 'docker'`
- Worker image must contain Docker CLI and the worker service must mount `/var/run/docker.sock`.

### Backend returns "The model `<name>` does not exist"
- This happens when the backend expects the real loaded model id/path while gateway forwarded an alias. The gateway/worker now rewrites `model` in backend payload to `model.source.value` so backend and switchboard naming stay consistent.

### Backend never becomes ready
- Inspect worker logs and backend logs:
```bash
cd /opt/llm-switchboard/docker
docker compose logs --tail=200 worker
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
docker logs --tail=200 llm-backend-<model-name>
```

### Auto-discovery does not find host model directories
- Keep weights in `/mnt/models`, `/opt/llm-switchboard/models`, or `/opt/llm-switchboard/model`, or mount additional host paths consistently into both `gateway` and `worker`.
