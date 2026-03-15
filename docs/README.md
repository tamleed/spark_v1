# LLM Switchboard for NVIDIA DGX Spark

> Русская версия с расширенными комментариями: `docs/README_RUS.md`.

## Deployment decision
- Public access mode: **Tailscale Funnel (`https://<node>.ts.net`) + API key**.
- Jupyter is **excluded** from this project scope.

## Quick deploy (copy-paste)
```bash
sudo mkdir -p /opt/llm-switchboard
sudo rsync -a ./ /opt/llm-switchboard/
cd /opt/llm-switchboard

./scripts/install_prereqs.sh
sudo cp .env.example /etc/llm-gateway.env
sudo nano /etc/llm-gateway.env

./scripts/pull_vllm_image.sh
./scripts/start_all.sh

./scripts/setup_tailscale_funnel.sh
./scripts/print_tailscale_urls.sh
```

## What to configure
### `/etc/llm-gateway.env`
```env
GATEWAY_API_KEY=<primary_key>
GATEWAY_API_KEYS=<key2,key3>     # optional multi-key list
ADMIN_API_KEY=<admin_primary>
ADMIN_API_KEYS=<admin2,admin3>   # optional multi-key list
ALLOW_PUBLIC_HEALTH=false
HF_TOKEN=
REDIS_URL=redis://127.0.0.1:6379/0
MODELS_YAML_PATH=/opt/llm-switchboard/configs/models.yaml
GATEWAY_YAML_PATH=/opt/llm-switchboard/configs/gateway.yaml
MODEL_DISCOVERY_DIRS=/opt/llm-switchboard/models:/opt/llm-switchboard/model:/mnt/models
```

### `configs/gateway.yaml`
- `security.require_api_key: true`
- `security.public_health_without_key: false`
- `network.public_access_mode: tailscale_funnel`

### `configs/models.yaml`
- add explicit models OR place weights into auto-discovery dirs.

## API usage (all implemented functions)
```bash
API_BASE="https://<your-node>.ts.net"
API_KEY="<user_key>"
ADMIN_KEY="<admin_key>"
```

### 1) `GET /health`
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/health"
```
Example response:
```json
{"ok": true, "redis": true}
```

### 2) `GET /v1/models`
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/v1/models"
```
Example response:
```json
{
  "object": "list",
  "data": [{"id": "qwen3-30b", "object": "model"}],
  "active_model": "qwen3-30b",
  "backend_state": "ready",
  "async_external_api": true
}
```

### 3) `POST /v1/chat/completions`
All request params (implemented):
- `model` (string, required)
- `messages` (array, required)
- `temperature` (number, optional)
- `max_tokens` (int, optional)
- `stream` (bool, optional)
- `async` (bool, optional, default=true)

```bash
curl -X POST "$API_BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "model":"qwen3-30b",
    "messages":[
      {"role":"system","content":"You are concise"},
      {"role":"user","content":"Hello"}
    ],
    "temperature":0.2,
    "max_tokens":128,
    "stream":false,
    "async":true
  }'
```
Async response example:
```json
{
  "status": "accepted",
  "job_id": "8f1...",
  "status_url": "/jobs/8f1...",
  "result_url": "/jobs/8f1.../result"
}
```

### 4) `POST /jobs`
Request params:
- `model`, `messages` required
- `temperature`, `max_tokens`, `stream` optional

```bash
curl -X POST "$API_BASE/jobs" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "model":"qwen3-30b",
    "messages":[{"role":"user","content":"Summarize text"}],
    "temperature":0.3,
    "max_tokens":256,
    "stream":false
  }'
```
Example response:
```json
{
  "id":"8f1...",
  "status":"queued",
  "requested_model":"qwen3-30b",
  "created_at":"2026-01-01T00:00:00+00:00",
  "started_at":null,
  "finished_at":null,
  "queue_position":1,
  "progress":null,
  "error":null
}
```

### 5) `GET /jobs/{id}`
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>"
```
Possible `status` values:
`queued | running | succeeded | failed | cancelled | not_completed`

### 6) `GET /jobs/{id}/result`
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>/result"
```
Success example:
```json
{
  "id":"chatcmpl-...",
  "object":"chat.completion",
  "choices":[{"index":0,"message":{"role":"assistant","content":"..."}}]
}
```

### 7) `POST /jobs/{id}/cancel`
```bash
curl -X POST -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>/cancel"
```
Example response:
```json
{"id":"8f1...","status":"cancelled"}
```

### 8) `GET /status` (admin)
```bash
curl -H "X-API-Key: $ADMIN_KEY" "$API_BASE/status"
```
Example:
```json
{"active_model":"qwen3-30b","switching":false,"backend_state":"ready","queue_length":0,"uptime":123,"containers_split":true}
```

### 9) `GET /queue` (admin)
```bash
curl -H "X-API-Key: $ADMIN_KEY" "$API_BASE/queue"
```
Example:
```json
{"queue_length":0,"current_job":null,"active_model":"qwen3-30b","switching":false,"drain_mode":false}
```

### 10) `POST /admin/switch` (admin)
```bash
curl -X POST "$API_BASE/admin/switch" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADMIN_KEY" \
  -d '{"model":"qwen3-30b"}'
```
Example:
```json
{"mode":"queued_admin_job","job_id":"..."}
```

### 11) `POST /admin/drain` (admin)
```bash
curl -X POST -H "X-API-Key: $ADMIN_KEY" "$API_BASE/admin/drain"
```
Example:
```json
{"drain_mode": true}
```

## Useful scripts
```bash
./scripts/setup_tailscale_funnel.sh
./scripts/print_tailscale_urls.sh
GATEWAY_API_KEY='<key>' ./scripts/smoke_test.sh
```
