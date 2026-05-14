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

## Полезные пути

- Документация: `docs/`.
- Контекст для ИИ: `docs/AI_CONTEXT.md`.
- Память проекта: `memory-bank/`.
