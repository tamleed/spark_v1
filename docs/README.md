# LLM Switchboard for NVIDIA DGX Spark

> Русскоязычная версия с расширенными комментариями: `docs/README_RUS.md`.

## Что внутри проекта

### Архитектура (разделена по контейнерам)
- `redis` container: очередь и хранилище статусов/результатов jobs.
- `gateway` container: внешний FastAPI API (`/v1/*`, `/jobs/*`, `/admin/*`).
- `worker` container: последовательное выполнение задач из RQ (concurrency=1).
- `vLLM backend` container: **динамически поднимается только для активной модели**.
- `jupyter` отдельно (systemd, localhost-only).

Это значит: падение модели не должно валить очередь или gateway.

### Каталоги
- `gateway/app/` — API, auth, маршруты, switcher, lock, прокси.
- `worker/` — воркер и фоновые задачи.
- `configs/` — `models.yaml`, `gateway.yaml`.
- `docker/` — compose + Dockerfile + DGX daemon example.
- `scripts/` — install/start/smoke/tailscale скрипты.
- `systemd/` — unit files (Jupyter и совместимость).

---

## Выбранный внешний доступ: `ts.net + API key`

Оставляем основной публичный режим:
- DGX публикует API через `tailscale funnel` (`https://<node>.ts.net`)
- Все API-запросы идут с заголовком `X-API-Key`
- `/health` тоже по ключу (по умолчанию)

Это работает без статического ISP IP (подходит при dynamic IP/CGNAT).

---

## Что и куда писать (обязательная настройка)

### 1) `/etc/llm-gateway.env`
```bash
sudo cp .env.example /etc/llm-gateway.env
sudo nano /etc/llm-gateway.env
```

Минимум заполнить:
```env
GATEWAY_API_KEY=<strong_random_key>
ADMIN_API_KEY=<separate_admin_key>
ALLOW_PUBLIC_HEALTH=false
REDIS_URL=redis://127.0.0.1:6379/0
MODELS_YAML_PATH=/opt/llm-switchboard/configs/models.yaml
GATEWAY_YAML_PATH=/opt/llm-switchboard/configs/gateway.yaml
MODEL_DISCOVERY_DIRS=/opt/llm-switchboard/models:/opt/llm-switchboard/model:/mnt/models
HF_TOKEN=<optional_if_hf_private>
```

### 2) `configs/models.yaml`
- Либо задайте модели явно,
- либо просто кладите каталоги с весами в `models/`, `model/` или `/mnt/models` — они автообнаруживаются.

### 3) `configs/gateway.yaml`
Убедиться, что:
- `network.public_access_mode: tailscale_funnel`
- `security.require_api_key: true`
- `security.public_health_without_key: false`

---

## Быстрый запуск

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

После этого используйте URL из funnel status:
`https://<your-node>.ts.net`

---

## Примеры API для всех функций

Ниже переменные:
```bash
API_BASE="https://<your-node>.ts.net"
API_KEY="<your_api_key>"
ADMIN_KEY="<your_admin_key>"
```

### 1) Health
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/health"
```

### 2) List models
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/v1/models"
```

### 3) Chat completion (async, по умолчанию)
```bash
curl -X POST "$API_BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "model":"qwen3-30b",
    "messages":[{"role":"user","content":"Привет"}],
    "temperature":0.2,
    "max_tokens":128,
    "async":true
  }'
```

### 4) Create job напрямую
```bash
curl -X POST "$API_BASE/jobs" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "model":"qwen3-30b",
    "messages":[{"role":"user","content":"Сделай краткое резюме"}],
    "max_tokens":256
  }'
```

### 5) Job status
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>"
```

### 6) Job result
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>/result"
```

### 7) Cancel job
```bash
curl -X POST -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>/cancel"
```

### 8) Extended status
```bash
curl -H "X-API-Key: $ADMIN_KEY" "$API_BASE/status"
```

### 9) Queue status
```bash
curl -H "X-API-Key: $ADMIN_KEY" "$API_BASE/queue"
```

### 10) Admin switch model
```bash
curl -X POST "$API_BASE/admin/switch" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADMIN_KEY" \
  -d '{"model":"qwen3-30b"}'
```

### 11) Admin drain mode
```bash
curl -X POST -H "X-API-Key: $ADMIN_KEY" "$API_BASE/admin/drain"
```

---

## Tailscale utility scripts

```bash
./scripts/setup_tailscale_funnel.sh
./scripts/print_tailscale_urls.sh
./scripts/setup_tailscale_serve_jupyter.sh
```

---

## Замечания по безопасности

- Не публикуйте API без ключа.
- Храните `GATEWAY_API_KEY` и `ADMIN_API_KEY` раздельно.
- Funnel (`*.ts.net`) — публичный интернет endpoint, поэтому ключ обязателен для всех endpoint.
