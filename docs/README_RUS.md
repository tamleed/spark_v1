# LLM Switchboard для NVIDIA DGX Spark (РУС)

> Режим по умолчанию: **Tailscale Funnel (`*.ts.net`) + API key**.
> Jupyter из текущего проекта исключён.

## Быстрый деплой
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

## Что и куда писать

### `/etc/llm-gateway.env`
```env
GATEWAY_API_KEY=<основной_ключ>
GATEWAY_API_KEYS=<ключ2,ключ3>     # опционально
ADMIN_API_KEY=<admin_ключ>
ADMIN_API_KEYS=<admin2,admin3>     # опционально
ALLOW_PUBLIC_HEALTH=false
HF_TOKEN=
REDIS_URL=redis://127.0.0.1:6379/0
MODELS_YAML_PATH=/opt/llm-switchboard/configs/models.yaml
GATEWAY_YAML_PATH=/opt/llm-switchboard/configs/gateway.yaml
MODEL_DISCOVERY_DIRS=/opt/llm-switchboard/models:/opt/llm-switchboard/model:/mnt/models
```

### `configs/gateway.yaml`
Проверьте:
- `security.require_api_key: true`
- `security.public_health_without_key: false`
- `network.public_access_mode: tailscale_funnel`

### `configs/models.yaml`
- либо явное описание моделей,
- либо складывайте веса в автопоиск (`models`, `model`, `/mnt/models`).

---

## Примеры API (все функции)

```bash
API_BASE="https://<your-node>.ts.net"
API_KEY="<user_key>"
ADMIN_KEY="<admin_key>"
```

### 1) Health
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/health"
```
Пример ответа:
```json
{"ok": true, "redis": true}
```

### 2) Список моделей
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/v1/models"
```
Пример:
```json
{
  "object":"list",
  "data":[{"id":"qwen3-30b","object":"model"}],
  "active_model":"qwen3-30b",
  "backend_state":"ready",
  "async_external_api":true
}
```

### 3) Chat completion
Параметры:
- `model` (обязательно)
- `messages` (обязательно)
- `temperature` (опц.)
- `max_tokens` (опц.)
- `stream` (опц.)
- `async` (опц., default=true)

```bash
curl -X POST "$API_BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "model":"qwen3-30b",
    "messages":[
      {"role":"system","content":"You are concise"},
      {"role":"user","content":"Привет"}
    ],
    "temperature":0.2,
    "max_tokens":128,
    "stream":false,
    "async":true
  }'
```
Пример ответа:
```json
{"status":"accepted","job_id":"8f1...","status_url":"/jobs/8f1...","result_url":"/jobs/8f1.../result"}
```

### 4) Создать job напрямую
```bash
curl -X POST "$API_BASE/jobs" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "model":"qwen3-30b",
    "messages":[{"role":"user","content":"Сделай резюме"}],
    "temperature":0.3,
    "max_tokens":256,
    "stream":false
  }'
```

### 5) Статус job
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>"
```
Возможные статусы:
`queued | running | succeeded | failed | cancelled | not_completed`

### 6) Результат job
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>/result"
```

### 7) Отмена job
```bash
curl -X POST -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>/cancel"
```

### 8) Расширенный статус (admin)
```bash
curl -H "X-API-Key: $ADMIN_KEY" "$API_BASE/status"
```

### 9) Очередь (admin)
```bash
curl -H "X-API-Key: $ADMIN_KEY" "$API_BASE/queue"
```

### 10) Переключение модели (admin)
```bash
curl -X POST "$API_BASE/admin/switch" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADMIN_KEY" \
  -d '{"model":"qwen3-30b"}'
```

### 11) Drain mode (admin)
```bash
curl -X POST -H "X-API-Key: $ADMIN_KEY" "$API_BASE/admin/drain"
```

---

## Полезные команды
```bash
./scripts/setup_tailscale_funnel.sh
./scripts/print_tailscale_urls.sh
GATEWAY_API_KEY='<key>' ./scripts/smoke_test.sh
```
