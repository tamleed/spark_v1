# LLM Switchboard for NVIDIA DGX Spark

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

## Ключевые кейсы (реализовано)

### 1) Автодобавление моделей из директории `models`/`model`
Теперь для добавления новой модели достаточно положить директорию с весами в:
- `/opt/llm-switchboard/models/<имя_модели>` или
- `/opt/llm-switchboard/model/<имя_модели>` или
- `/mnt/models/<имя_модели>`

И вызывать API с `model: "<имя_директории>"`.
Модель автоматически появляется в `/v1/models`.

### 2) Таймаут ожидания ответа модели (по умолчанию 4 минуты)
- `inference_timeout_sec: 240` в `configs/gateway.yaml`.
- Если модель не ответила за timeout: job помечается как `not_completed` и в API возвращается `не выполнено`.

### 3) Переполнение памяти (OOM)
- При обнаружении OOM:
  - backend контейнер модели принудительно останавливается,
  - job возвращается как `не выполнено` (статус `not_completed`),
  - система остаётся готовой к следующим задачам.

### 4) Асинхронное внешнее API
- `POST /v1/chat/completions` (по умолчанию async) возвращает `job_id`.
- Дальше внешний клиент опрашивает:
  - `GET /jobs/{id}`
  - `GET /jobs/{id}/result`
- Это полноценный async workflow для внешних клиентов.

---

## Быстрый старт (DGX Spark)

```bash
sudo mkdir -p /opt/llm-switchboard
sudo rsync -a ./ /opt/llm-switchboard/
cd /opt/llm-switchboard

./scripts/install_prereqs.sh
sudo cp .env.example /etc/llm-gateway.env
sudo nano /etc/llm-gateway.env

# при необходимости поправьте configs/models.yaml и configs/gateway.yaml
./scripts/pull_vllm_image.sh
./scripts/start_all.sh
```

Проверка:
```bash
GATEWAY_API_KEY='<your-key>' ./scripts/smoke_test.sh
```

---

## Docker для DGX Spark

`install_prereqs.sh`:
- ставит `nvidia-container-toolkit`,
- делает `nvidia-ctk runtime configure --runtime=docker`,
- применяет `/etc/docker/daemon.json` (пример в `docker/daemon.json.dgx.example`).

Проверка GPU в контейнере:
```bash
cd docker
docker compose --profile dgx-check up --abort-on-container-exit dgx-gpu-check
```

---


## Сеть DGX без статического IP

DGX Spark может работать без публичного статического IP (включая CGNAT), если есть Tailscale:
- Публичный API: через `tailscale funnel` на `*.ts.net`
- Приватный доступ (Jupyter/admin): через `tailscale serve` и/или SSH через tailnet
- Используйте Tailscale IP/DNS устройства, а не ISP IP

Проверить текущий Tailscale IP/DNS:
```bash
./scripts/print_tailscale_urls.sh
```

## Tailscale

### Публичный API (Funnel)
```bash
./scripts/setup_tailscale_funnel.sh
./scripts/print_tailscale_urls.sh
```

### Jupyter tailnet-only
```bash
./scripts/setup_tailscale_serve_jupyter.sh
./scripts/print_tailscale_urls.sh
```

---

## API примеры

```bash
curl http://127.0.0.1:8000/health
curl -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/v1/models

curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $GATEWAY_API_KEY" \
  -d '{"model":"qwen3-30b","messages":[{"role":"user","content":"hello"}],"max_tokens":128,"async":true}'

curl -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/jobs/<job_id>
curl -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/jobs/<job_id>/result
curl -X POST -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/jobs/<job_id>/cancel
```
