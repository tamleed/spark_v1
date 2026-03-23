# LLM Switchboard для NVIDIA DGX Spark (РУС)

## Architecture
- `gateway` — HTTP/API слой. Принимает запросы, валидирует ключи, публикует `/v1/chat/completions`, `/jobs/*`, `/status`, `/queue`.
- `worker` — **контейнерный orchestrator** backend-контейнеров. Он забирает job из Redis/RQ, переключает модель и управляет backend-контейнерами через Docker daemon хоста.
- `ModelSwitcher` останавливает старый backend, запускает новый vLLM backend-контейнер, ждёт readiness через `/v1/models`, затем inference идёт через proxy.
- `redis` хранит очередь и метаданные job.

## Заметки по DGX Spark
- DGX Spark — это ARM64 / Blackwell платформа. Для неё нужен **совместимый** backend image vLLM.
- Выбор backend image происходит так:
  1. `backend.image` в `configs/models.yaml`
  2. `VLLM_IMAGE`
  3. `inference_backend.default_image` в `configs/gateway.yaml`
- В репозитории по умолчанию стоит `nvcr.io/nvidia/vllm:26.02-py3`, но на Spark это надо валидировать под ваш стек и при необходимости переопределять.
- Worker-контейнеру нужны:
  - Docker CLI внутри image,
  - mounted `/var/run/docker.sock`,
  - mounted директории моделей.

## Быстрый деплой
```bash
sudo mkdir -p /opt/llm-switchboard
sudo rsync -a ./ /opt/llm-switchboard/
cd /opt/llm-switchboard

./scripts/install_prereqs.sh
sudo cp .env.example /etc/llm-gateway.env
sudo nano /etc/llm-gateway.env

./scripts/pull_vllm_image.sh   # только prefetch
./scripts/start_all.sh
```

## Обязательные переменные
`/etc/llm-gateway.env`
```env
GATEWAY_API_KEY=<user_key>
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

## Runtime / compose
- `docker compose up -d` поднимает `redis`, `gateway`, `worker`.
- `worker` запускается как `python -m worker.worker` и имеет доступ к Docker socket.
- `gateway` и `worker` используют `PYTHONPATH=/app:/app/gateway`, поэтому импорты пакетов консистентны.
- `pull_vllm_image.sh` — это только prefetch helper; реальный backend image выбирается в runtime из model config/env.

## Как работает model switching
1. Клиент вызывает `POST /v1/chat/completions`.
2. Gateway ставит `worker.tasks.execute_chat_job` в очередь.
3. Worker переводит job в `running`, вызывает `ensure_model_active()` и выбирает модель.
4. `ModelSwitcher` останавливает старый backend, запускает новый vLLM backend-контейнер с GPU-флагами и ждёт ответа `http://127.0.0.1:<port>/v1/models`.
5. После readiness worker проксирует inference в backend.

## Проверки / readiness
### Базовые сервисы
```bash
cd /opt/llm-switchboard/docker
docker compose ps
curl -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/health
```

### Проверка worker runtime
```bash
./scripts/check_worker_runtime.sh
```
Скрипт проверяет:
- `docker ps` внутри `worker`,
- `import worker.tasks`,
- `from gateway.app.config import load_config`.

### Проверка GPU
```bash
cd /opt/llm-switchboard/docker
docker compose --profile dgx-check up dgx-gpu-check
```

### Проверка model registry / switching
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
Smoke test проверяет enqueue/poll/cancel. Имена моделей в smoke test должны совпадать с вашим deployment.

## Troubleshooting
### `module 'worker' has no attribute 'tasks'`
- Убедитесь, что есть `worker/__init__.py` и worker запускается как `python -m worker.worker`.

### `FileNotFoundError: 'docker'`
- В worker image должен быть Docker CLI, а в worker service — mounted `/var/run/docker.sock`.

### Backend не становится ready
- Смотрите логи worker и backend-контейнера:
```bash
cd /opt/llm-switchboard/docker
docker compose logs --tail=200 worker
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
docker logs --tail=200 llm-backend-<model-name>
```

### Автопоиск моделей не видит директории
- Автопоиск работает только по mounted директориям. Держите веса в `/mnt/models`, `/opt/llm-switchboard/models`, `/opt/llm-switchboard/model` или монтируйте дополнительные host paths консистентно.
