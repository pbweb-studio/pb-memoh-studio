# Runbook: Windows / локальная разработка

## Предпосылки

- Windows 10/11.
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) с WSL2 backend (рекомендуется).
- Git, Cursor.

## Секреты

1. Скопируйте `.env.example` → `.env.local` (если файла ещё нет — его создаст агент при необходимости).
2. Заполните ключи (OpenAI, Telegram и т.д.) по мере готовности фич; без секретов можно поднимать только инфраструктуру.

## Инфраструктура Studio (Postgres + Redis + studio-api + Celery)

Из корня репозитория (агент выполняет сам):

```powershell
docker compose -f docker-compose.local.yml up -d --build
```

Сервисы: `studio-postgres`, `studio-redis`, одноразовый `studio-migrate` (Alembic), `studio-api` (uvicorn), `studio-worker`, `studio-beat`.

Переменные `POSTGRES_*`, `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL` должны быть согласованы между `.env.local` и compose (в compose заданы значения по умолчанию для Docker-сети; на хосте для локального pytest без Docker используйте порты **5433** / **6380** как в `.env.example`).

Проверка API:

```powershell
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/events/telegram -H "Content-Type: application/json" -d "{\"update_id\": 1, \"message\": {\"message_id\": 1, \"date\": 1700000000, \"chat\": {\"id\": -100, \"type\": \"supergroup\", \"title\": \"T\"}, \"from\": {\"id\": 42, \"is_bot\": false, \"first_name\": \"U\"}, \"text\": \"hi\"}}"
```

(При занятом порту 8000 задайте `STUDIO_API_PORT` в `.env.local` или в окружении перед `docker compose`.)

## Тесты Python-пакета Studio

Локально без установленного Python 3.12 — прогон тестов Studio в Docker:

```powershell
docker run --rm -v "${PWD}/studio:/app" -w /app python:3.12-slim bash -c "pip install -q -e '.[dev]' && pytest tests/ -v"
```

(Из корня репозитория `pb-memoh-studio`; на Windows путь к `studio` подставьте свой.)

Локальный Redis студии по умолчанию слушает **6380** на хосте (см. `STUDIO_REDIS_PORT` в `docker-compose.local.yml`), чтобы не конфликтовать с другим Redis. Пример `REDIS_URL`: `redis://127.0.0.1:6380/0`.

## Memoh

Штатный запуск Memoh — по документации upstream (`docker-compose.yml` в корне или `docker/`). На Фазе 0 слой студии не подключается к Memoh автоматически.

### Event Mirror из Memoh (фаза 4b, вариант C)

По умолчанию зеркало **выключено** (`MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED=false`). Чтобы Memoh дублировал сырой Telegram `Update` в Studio, задайте в окружении агента:

- `STUDIO_EVENTS_URL` — полный URL ingest (например `http://127.0.0.1:8000/events/telegram` при поднятом `studio-api`);
- `MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED=true`;
- `MEMOH_TELEGRAM_EVENT_MIRROR_TIMEOUT_MS` (по умолчанию 1000);
- `MEMOH_STUDIO_EVENTS_TOKEN` или общий `STUDIO_EVENTS_INGEST_TOKEN` для заголовка `Authorization: Bearer …`.

Переменные перечислены в корневом `.env.example`. Тесты Go-пакета адаптера:

```powershell
go test ./internal/channel/adapters/telegram/... -count=1
```

## Studio: управляющая группа (фаза 5a)

- Переменная **`STUDIO_ADMIN_TOKEN`**: если задана, эндпоинты `GET /control-group`, `POST /control-group/set`, `GET /chats`, `GET /chats/unassigned`, `POST /chats/{studio_chat_uuid}/role` требуют заголовок `Authorization: Bearer <token>`. Если пусто — локально роуты открыты (осторожно в публичной сети).
- Пример назначения control group (после того как чат уже появился в БД через `POST /events/telegram`):

```powershell
curl -X POST http://127.0.0.1:8000/control-group/set -H "Content-Type: application/json" -d "{\"telegram_chat_id\": -1001234567890}"
```

## Полезные пути

- Документация: `docs/`.
- Контекст для ИИ: `docs/AI_CONTEXT.md`.
- Память проекта: `memory-bank/`.
