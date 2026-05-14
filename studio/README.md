# Studio Layer (Python)

Пакет **`pb_studio`** — слой студии поверх Memoh. **Фаза 2a:** Response Queue (модели, `QueueService`, тесты) без Memoh и Telegram. **Фаза 3:** каркас `studio-api` (FastAPI), Postgres/Redis, SQLAlchemy async session, Alembic, Celery worker/beat, Docker Compose.

## Установка (разработка)

```bash
cd studio
python -m pip install -e ".[dev]"
pytest
```

## Локальный Docker (Postgres, Redis, API, migrate, worker, beat)

Из корня репозитория:

```bash
docker compose -f docker-compose.local.yml up -d --build
```

- HTTP: `http://127.0.0.1:8000/health` (порт задаётся `STUDIO_API_PORT`).
- Миграции: одноразовый сервис `studio-migrate` (`alembic upgrade head`) перед стартом API/worker.

Вручную из каталога `studio` (нужен запущенный Postgres с URL из `.env.local`):

```bash
alembic upgrade head
uvicorn pb_studio.api.main:app --reload --host 0.0.0.0 --port 8000
celery -A pb_studio.celery_app:celery_app worker --loglevel=info --queues=studio
celery -A pb_studio.celery_app:celery_app beat --loglevel=info
```

## Response Queue (внутренний сервис Studio)

- Модели: `pb_studio.response_queue.models`
- Логика: `pb_studio.response_queue.service.QueueService`
- Статусы: `pb_studio.response_queue.statuses`

Справочный SQL: `studio/migrations/001_response_queue.sql`. Основной путь схемы — **Alembic** (`studio/alembic/`).
