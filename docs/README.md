# LLM Switchboard for NVIDIA DGX Spark

## 1) Overview
LLM Switchboard — это FastAPI + Redis/RQ сервис для управления несколькими LLM через OpenAI-like API с **жёсткой гарантией: в памяти одновременно активна только одна модель**.

Почему так:
- На ограниченной GPU/VRAM-конфигурации безопаснее держать только один vLLM backend.
- Переключение модели выполняется остановкой текущего контейнера (`docker stop/kill`) и запуском нового.
- Очередь задач и один worker (`RQ`, concurrency=1) устраняют гонки при switch.

Компоненты:
- `gateway` — API, маршруты OpenAI/jobs/admin.
- `worker` — последовательное выполнение задач, switch + inference.
- `redis` — брокер очереди и хранение job metadata/results.
- `vLLM` — inference backend в Docker (один контейнер в любой момент).
- `tailscale funnel/serve` — внешний API и приватный Jupyter.

## 2) Quickstart (DGX Spark)
> Ниже предполагается, что проект находится в `/opt/llm-switchboard`.

### Шаг 0. Копирование проекта
```bash
sudo mkdir -p /opt/llm-switchboard
sudo rsync -a ./ /opt/llm-switchboard/
cd /opt/llm-switchboard
```

### Шаг 1. Установка prereqs
```bash
./scripts/install_prereqs.sh
```


### Важно: Docker-профиль именно для DGX Spark
Скрипт `install_prereqs.sh` дополнительно делает DGX-специфичную настройку:
- устанавливает `nvidia-container-toolkit`,
- выполняет `nvidia-ctk runtime configure --runtime=docker`,
- кладёт пример `/etc/docker/daemon.json` с `default-runtime: nvidia`,
- перезапускает Docker.

Проверка:
```bash
docker info | rg -i "Runtimes|Default Runtime"
docker run --rm --runtime=nvidia --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```


### Шаг 2. Настройка env
```bash
sudo cp .env.example /etc/llm-gateway.env
sudo nano /etc/llm-gateway.env
```
Минимум задайте:
- `GATEWAY_API_KEY`
- `ADMIN_API_KEY`
- `HF_TOKEN` (если нужен приватный HF)
- `MODELS_YAML_PATH=/opt/llm-switchboard/configs/models.yaml`
- `GATEWAY_YAML_PATH=/opt/llm-switchboard/configs/gateway.yaml`

### Шаг 3. Настройка моделей
Отредактируйте `configs/models.yaml`:
- проставьте реальные `source.value` (repo id или локальный путь),
- при необходимости скорректируйте `vllm_args`, `quantization.method`, `max-model-len`.

### Шаг 4. Pull образа vLLM
```bash
./scripts/pull_vllm_image.sh
```

### Шаг 5. (Опционально) скачать модели заранее
```bash
./scripts/download_models.sh
```

### Шаг 6. Запуск сервисов
```bash
./scripts/start_all.sh
```

### Шаг 7. Smoke test
```bash
GATEWAY_API_KEY='<your-key>' ./scripts/smoke_test.sh
```

## 3) Модели и конфигурация
### `configs/models.yaml`
Каждая модель задаётся блоком:
- `name` — логическое имя (используется в API)
- `source.type` = `local_path | huggingface_repo`
- `source.value` — путь или HF repo
- `backend.image` — docker image для vLLM
- `backend.port` — локальный порт vLLM
- `backend.vllm_args` — список аргументов
- `quantization.method` — для 4bit моделей (`awq/gptq/...`)

Для `qwen3-235b-4bit` дефолт:
- `--max-model-len 4096`
- `--max-num-seqs 1`
- `--quantization awq`

### `configs/gateway.yaml`
Ключевые разделы:

### DGX-оптимизированный запуск vLLM контейнера
По умолчанию switcher запускает backend с параметрами, удобными для DGX Spark:
- `--runtime nvidia`, `--gpus all`
- `--network host`, `--ipc host`
- `--shm-size 16g`
- `--ulimit memlock=-1`, `--ulimit stack=67108864`

Все эти параметры меняются через `configs/gateway.yaml` (`docker.*`) и/или env (`DOCKER_RUNTIME`, `DOCKER_NETWORK_MODE`, `DOCKER_SHM_SIZE`, `DOCKER_IPC_MODE`).

- `policies` — async/sync правила и `max_tokens_upper_bound`
- `switching` — timeout’ы switch/readiness/stop
- `inference` — timeout inference
- `locks.file_lock_path` — файловый lock
- `security` — API-key и CORS политика
- `network.public_access_mode` — `tailscale_funnel | tailnet_only`

## 4) Публичный API через Tailscale Funnel (`*.ts.net`)
Включить:
```bash
./scripts/setup_tailscale_funnel.sh
./scripts/print_tailscale_urls.sh
```

Проверить:
```bash
curl https://<your>.ts.net/health
curl -H "X-API-Key: <key>" https://<your>.ts.net/v1/models
```

Отключить:
```bash
sudo tailscale funnel reset
```

> Funnel публичный интернет: **обязательно используйте API key**.

## 5) JupyterLab и удалённая разработка
Jupyter поднимается как systemd unit (`127.0.0.1:8888`, token auth включён).

Включить tailnet-only публикацию:
```bash
./scripts/setup_tailscale_serve_jupyter.sh
./scripts/print_tailscale_urls.sh
```

### Вариант A: SSH port-forward
```bash
ssh -L 8888:127.0.0.1:8888 <user>@<dgx-tailscale-host>
```
Открыть в браузере `http://127.0.0.1:8888` и ввести токен.

### Вариант B: VS Code Remote-SSH
1. Подключиться к DGX по Tailscale hostname/IP.
2. Открыть `/home/<user>/work`.
3. Выбрать Python интерпретатор на DGX (`/opt/llm-switchboard/.venv/bin/python`).

### Вариант C: PyCharm Remote Interpreter
1. Настроить SSH interpreter на DGX.
2. Указать venv `/opt/llm-switchboard/.venv/bin/python`.

### Подключение к удалённому Jupyter из IDE
Используйте URL tailnet-only/локальный tunnel, например `http://127.0.0.1:8888/?token=<token>`.

## 6) API примеры (`curl`)
```bash
# health (может быть без ключа)
curl http://127.0.0.1:8000/health

# models
curl -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/v1/models

# async chat completion
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $GATEWAY_API_KEY" \
  -d '{
    "model": "gpt-oss120",
    "messages": [{"role":"user","content":"Hello"}],
    "temperature": 0.2,
    "max_tokens": 128,
    "stream": false,
    "async": true
  }'

# job status
curl -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/jobs/<job_id>

# job result
curl -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/jobs/<job_id>/result

# cancel job
curl -X POST -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/jobs/<job_id>/cancel

# status
curl -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/status

# queue (admin)
curl -H "X-API-Key: $ADMIN_API_KEY" http://127.0.0.1:8000/queue
```

## 7) Troubleshooting
### Логи сервисов
```bash
journalctl -u llm-gateway.service -f
journalctl -u llm-worker.service -f
journalctl -u jupyter.service -f
```

### Логи vLLM backend контейнера
```bash
docker ps -a | grep llm-backend
docker logs -f <container_name>
```

### Redis недоступен
- Проверьте `docker compose ps` в `docker/`.
- Проверьте `REDIS_URL` в `/etc/llm-gateway.env`.

### Модель не стартует / OOM
- Уменьшите `--max-model-len` и/или `--max-num-seqs`.
- Проверьте корректность quantization параметров.

### Switch timeout
- Увеличьте `switching.backend_ready_timeout_sec`.
- Проверьте `docker logs` backend контейнера.

### Cancel поведение
- `queued` job удаляется из очереди и помечается cancelled.
- `running` job вызывает `docker stop/kill` backend контейнера (hard cancel).

### Вручную остановить backend контейнер
```bash
docker ps -a | grep llm-backend
docker stop <container>
docker rm -f <container>
```
