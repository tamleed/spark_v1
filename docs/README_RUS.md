# LLM Switchboard для NVIDIA DGX Spark (РУС)

## Architecture
- `gateway` принимает HTTP/API запросы и публикует `/v1/chat/completions`, `/jobs/*`, `/status`, `/queue`.
- `worker` — контейнерный orchestrator: он забирает job из Redis/RQ, через `ModelSwitcher` останавливает старый backend-контейнер, запускает новый vLLM backend-контейнер, ждёт readiness и затем проксирует inference.
- `redis` хранит очередь и метаданные job.
- Backend-контейнеры моделей **динамические**: это не постоянные compose-сервисы, их запускает worker через Docker daemon хоста.

## Заметки по DGX Spark
- DGX Spark — ARM64 / Blackwell платформа. Для неё нужен совместимый backend image vLLM.
- Backend image выбирается так:
  1. `backend.image` в `configs/models.yaml`
  2. `VLLM_IMAGE`
  3. `inference_backend.default_image` в `configs/gateway.yaml`
- В репозитории по умолчанию стоит `nvcr.io/nvidia/vllm:26.02-py3`. На Spark этот тег нужно валидировать под ваш стек и при необходимости переопределять.
- Worker-контейнеру нужны:
  - Docker CLI внутри image,
  - mounted `/var/run/docker.sock`,
  - mounted директории моделей,
  - host networking для обращения к backend по `127.0.0.1:<port>`.

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
- `worker` запускается как `python -m worker.worker`.
- `gateway` и `worker` используют `PYTHONPATH=/app:/app/gateway`.
- `gateway` и `worker` монтируют директории автопоиска моделей, поэтому список моделей может обновляться без рестарта стека.
- `pull_vllm_image.sh` — только prefetch helper; реальный backend image выбирается в runtime из model config/env.

## Как работает model switching
1. Клиент вызывает `POST /v1/chat/completions`.
2. Gateway ставит `worker.tasks.execute_chat_job` в очередь.
3. Worker переводит job в `running`, выбирает модель и вызывает `ensure_model_active()`.
4. `ModelSwitcher` останавливает старый backend-контейнер, запускает новый vLLM backend-контейнер с GPU-флагами и ждёт ответа `http://127.0.0.1:<port>/v1/models`.
5. После readiness worker проксирует inference в backend и сохраняет результат в job.

## Подхват моделей из директории без рестарта
Hot discovery работает потому, что `/v1/models` пересобирает список моделей на каждый запрос, а compose-сервисы теперь видят mounted директории моделей.

### Как добавить модель в уже запущенный сервис
1. Положите новую модель в одну из директорий автопоиска, например:
```bash
mkdir -p /opt/llm-switchboard/models/my-new-model
# скопируйте файлы модели в /opt/llm-switchboard/models/my-new-model
```
2. Повторно запросите список моделей:
```bash
curl -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/v1/models
```
3. Имя новой директории должно появиться как `model id` без рестарта `gateway` или `worker`.

### Автоматическая проверка hot discovery
```bash
API_URL=http://127.0.0.1:8000 \
GATEWAY_API_KEY='<key>' \
./scripts/check_hot_model_discovery.sh
```
Скрипт создаёт временную директорию модели под `/opt/llm-switchboard/models`, повторно вызывает `/v1/models` и проверяет, что модель появилась без рестарта стека.

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

### Smoke test lifecycle после restart gateway/worker
```bash
API_URL=http://127.0.0.1:8000 \
GATEWAY_API_KEY='<key>' \
./scripts/check_backend_lifecycle_restart.sh
```
Скрипт создаёт backend/job, перезапускает `gateway` и `worker`, потом отправляет повторную job и проверяет, что не возникает `Conflict. The container name ... is already in use`.

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

## API-запросы для тестирования
### Локально на сервере
```bash
API_BASE="http://127.0.0.1:8000"
API_KEY="$GATEWAY_API_KEY"
ADMIN_KEY="$ADMIN_API_KEY"
```

#### Health
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/health"
```

#### Список моделей
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

### Реальный сценарий: спросить у одной модели, потом у другой
Ниже полностью готовый набор команд (скопируйте и запустите по шагам).

1) Посмотрите доступные модели и выберите два `id`:
```bash
curl -s -H "X-API-Key: $API_KEY" "$API_BASE/v1/models" | jq -r '.data[].id'
```

2) Отправьте вопрос в первую модель (замените `MODEL_A`):
```bash
MODEL_A="gpt-oss-20b"
JOB1=$(curl -s -X POST "$API_BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d "{
    \"model\":\"$MODEL_A\",
    \"messages\":[{\"role\":\"user\",\"content\":\"Кратко объясни, что такое RAG и когда он нужен.\"}],
    \"stream\":false,
    \"async\":true
  }" | jq -r '.job_id')
echo "JOB1=$JOB1"
```

3) Дождитесь завершения первой job и получите ответ:
```bash
until [[ "$(curl -s -H "X-API-Key: $API_KEY" "$API_BASE/jobs/$JOB1" | jq -r '.status')" == "succeeded" ]]; do
  echo "waiting for $JOB1..."
  sleep 2
done
curl -s -H "X-API-Key: $API_KEY" "$API_BASE/jobs/$JOB1/result" | jq
```

4) Отправьте второй вопрос во вторую модель (замените `MODEL_B`):
```bash
MODEL_B="qwen2.5-7b-instruct"
JOB2=$(curl -s -X POST "$API_BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d "{
    \"model\":\"$MODEL_B\",
    \"messages\":[{\"role\":\"user\",\"content\":\"Сделай сравнение RAG и fine-tuning в 5 пунктах.\"}],
    \"stream\":false,
    \"async\":true
  }" | jq -r '.job_id')
echo "JOB2=$JOB2"
```

5) Дождитесь завершения второй job и получите ответ:
```bash
until [[ "$(curl -s -H "X-API-Key: $API_KEY" "$API_BASE/jobs/$JOB2" | jq -r '.status')" == "succeeded" ]]; do
  echo "waiting for $JOB2..."
  sleep 2
done
curl -s -H "X-API-Key: $API_KEY" "$API_BASE/jobs/$JOB2/result" | jq
```

> Важно: для разных моделей отправляйте **разные async job**. Worker сам переключит backend-контейнер между `MODEL_A` и `MODEL_B`.

#### Статус / результат job
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>"
curl -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>/result"
```

#### Admin status / queue
```bash
curl -H "X-API-Key: $ADMIN_KEY" "$API_BASE/status"
curl -H "X-API-Key: $ADMIN_KEY" "$API_BASE/queue"
```

### С другого компьютера через доменное имя
Подставьте ваш реальный домен, например Tailscale Funnel host или имя reverse proxy.

```bash
API_BASE="https://api.example.com"
API_KEY="<gateway_key>"
ADMIN_KEY="<admin_key>"
```

#### Health
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/health"
```

#### Список моделей
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

#### Статус / результат job
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>"
curl -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>/result"
```

#### Admin status / queue
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
Smoke test проверяет enqueue, poll и cancel. При необходимости скорректируйте имена моделей под ваш deployment.

## Troubleshooting
### `module 'worker' has no attribute 'tasks'`
- Убедитесь, что есть `worker/__init__.py` и worker запускается как `python -m worker.worker`.

### `FileNotFoundError: 'docker'`
- В worker image должен быть Docker CLI, а в worker service — mounted `/var/run/docker.sock`.

### Backend возвращает "The model `<name>` does not exist"
- Это происходит, когда backend ожидает реальный идентификатор/путь модели, а gateway отправил алиас. Gateway/worker теперь переписывают `model` в backend payload на `model.source.value`, чтобы имена в switchboard и backend совпадали.

### Backend не становится ready
- Смотрите логи worker и backend:
```bash
cd /opt/llm-switchboard/docker
docker compose logs --tail=200 worker
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
docker logs --tail=200 llm-backend-<model-name>
```

### Автопоиск не видит директории моделей
- Держите веса в `/mnt/models`, `/opt/llm-switchboard/models`, `/opt/llm-switchboard/model` или монтируйте дополнительные host paths одновременно в `gateway` и `worker`.
