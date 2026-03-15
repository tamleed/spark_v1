# LLM Switchboard для NVIDIA DGX Spark (РУС)

> Этот файл — русскоязычная версия документации с поясняющими комментариями.
> Основной режим публикации API: **Tailscale Funnel (`*.ts.net`) + `X-API-Key`**.

---

## 1. Что это за проект

LLM Switchboard — сервис-оркестратор для нескольких LLM, где:
- одновременно активна только **одна** модель в памяти;
- запросы выполняются через очередь (Redis + RQ);
- при смене модели старый backend-контейнер останавливается, новый запускается;
- API совместим по стилю с OpenAI (`/v1/models`, `/v1/chat/completions`).

### Почему так сделано
- На DGX Spark память ограничена; безопаснее держать только один backend модели.
- Изоляция по контейнерам предотвращает «падение всего стека» при проблеме одной модели.

---

## 2. Архитектура контейнеров

Постоянные контейнеры:
1. `redis` — очередь и метаданные задач.
2. `gateway` — внешний API и контроль состояния.
3. `worker` — последовательное выполнение задач (по сути concurrency=1 на обработке).

Динамический контейнер:
4. `vLLM backend` — поднимается только для активной модели.

Дополнительно:
- `dgx-gpu-check` — служебный профиль для проверки GPU (`nvidia-smi`).
- Jupyter запускается отдельно как `systemd` сервис (localhost-only).

---

## 3. Сеть без статического IP (важно)

Если у DGX нет статического публичного IP (dynamic/CGNAT), используем:
- **Публичный API:** `tailscale funnel` → `https://<node>.ts.net`
- **Приватный доступ:** tailnet (`tailscale serve`, SSH)

То есть внешний доступ идёт не через ISP IP, а через инфраструктуру Tailscale.

---

## 4. Что и куда писать (обязательно)

### 4.1 Файл окружения
Создайте и заполните:
```bash
sudo cp .env.example /etc/llm-gateway.env
sudo nano /etc/llm-gateway.env
```

Минимально:
```env
GATEWAY_API_KEY=<сильный_ключ>
ADMIN_API_KEY=<отдельный_admin_ключ>
ALLOW_PUBLIC_HEALTH=false
REDIS_URL=redis://127.0.0.1:6379/0
MODELS_YAML_PATH=/opt/llm-switchboard/configs/models.yaml
GATEWAY_YAML_PATH=/opt/llm-switchboard/configs/gateway.yaml
MODEL_DISCOVERY_DIRS=/opt/llm-switchboard/models:/opt/llm-switchboard/model:/mnt/models
HF_TOKEN=<опционально>
```

### 4.2 Конфиг моделей
`configs/models.yaml`:
- можно явно задать модели,
- либо просто положить папку с весами в один из каталогов автопоиска.

### 4.3 Конфиг gateway
`configs/gateway.yaml` (проверьте):
- `network.public_access_mode: tailscale_funnel`
- `security.require_api_key: true`
- `security.public_health_without_key: false`

---

## 5. Быстрый запуск

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

После этого API обычно доступен по:
```text
https://<your-node>.ts.net
```

---

## 6. Добавление новой модели (самый частый кейс)

### Вариант A: через автопоиск папок
1. Поместите веса в:
   - `/opt/llm-switchboard/models/<имя_модели>`
   - или `/opt/llm-switchboard/model/<имя_модели>`
   - или `/mnt/models/<имя_модели>`
2. Используйте в API `"model": "<имя_модели>"`.
3. Проверьте, что модель появилась:
   ```bash
   curl -H "X-API-Key: $API_KEY" "$API_BASE/v1/models"
   ```

### Вариант B: через `configs/models.yaml`
Добавьте явный блок модели (source/backend/vllm_args), перезапустите сервисы.

---

## 7. Примеры API (все основные функции)

Подготовим переменные:
```bash
API_BASE="https://<your-node>.ts.net"
API_KEY="<your_api_key>"
ADMIN_KEY="<your_admin_key>"
```

### 7.1 Проверка здоровья
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/health"
```

### 7.2 Список моделей
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/v1/models"
```

### 7.3 Создать async chat completion
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

### 7.4 Создать job напрямую
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

### 7.5 Статус job
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>"
```

### 7.6 Результат job
```bash
curl -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>/result"
```

### 7.7 Отмена job
```bash
curl -X POST -H "X-API-Key: $API_KEY" "$API_BASE/jobs/<job_id>/cancel"
```

### 7.8 Расширенный статус (admin)
```bash
curl -H "X-API-Key: $ADMIN_KEY" "$API_BASE/status"
```

### 7.9 Состояние очереди (admin)
```bash
curl -H "X-API-Key: $ADMIN_KEY" "$API_BASE/queue"
```

### 7.10 Ручной switch модели (admin)
```bash
curl -X POST "$API_BASE/admin/switch" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADMIN_KEY" \
  -d '{"model":"qwen3-30b"}'
```

### 7.11 Включить drain mode (admin)
```bash
curl -X POST -H "X-API-Key: $ADMIN_KEY" "$API_BASE/admin/drain"
```

---

## 8. Таймауты и ошибки

- Если модель долго не отвечает (по умолчанию ~4 минуты), задача уходит в `not_completed` (`не выполнено`).
- При OOM backend модели принудительно останавливается, чтобы система могла продолжить работу с другими задачами.

---

## 9. Полезные команды эксплуатации

```bash
# статус tailscale/funnel/serve
./scripts/print_tailscale_urls.sh

# включить публичный funnel
./scripts/setup_tailscale_funnel.sh

# tailnet-only публикация Jupyter
./scripts/setup_tailscale_serve_jupyter.sh

# базовый smoke
GATEWAY_API_KEY='<key>' ./scripts/smoke_test.sh
```

---

## 10. Рекомендации по безопасности

1. Не используйте одинаковый ключ для user/admin.
2. Регулярно ротируйте API ключи.
3. Не публикуйте служебные endpoint’ы без ключа.
4. Для критичных сценариев добавьте внешний rate limit / WAF.
