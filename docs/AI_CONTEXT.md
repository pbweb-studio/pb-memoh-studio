# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 3 завершена** — каркас Studio Layer: FastAPI `studio-api` (`GET /health`), Pydantic Settings, async Postgres (SQLAlchemy), Redis, Alembic, Celery app + worker/beat skeleton, Docker Compose local (`studio-api`, `studio-worker`, `studio-beat`, `studio-migrate`, Postgres, Redis). Response Queue остаётся **внутренним** сервисом Studio без Memoh и без Telegram runtime.

Дальше: **Фаза 4 — Event Mirror** (зеркалирование событий в Studio; без реализации в Фазе 3).

## Текущая цель

Реализовать **Event Mirror** и связать его с жизненным циклом Studio (включая очередь ответов там, где это уместно по ADR) — в рамках Фазы 4, после отдельного плана и без правок Memoh до зафиксированного варианта A/B/C.

## Что уже работает

- Фазы 0–2a: bootstrap, разведка Memoh, Response Queue core (см. историю в `docs/04_PROJECT_LOG.md`).
- **Фаза 3:** пакет [`studio/pb_studio/`](studio/pb_studio/) — `api/main.py`, `core/config.py`, `core/database.py`, `core/redis_client.py`, `celery_app.py`, `worker/tasks.py`, Alembic `001_initial`, Dockerfile, `docker-compose.local.yml` с сервисами Studio; smoke-тесты Фазы 3.

## Что ещё не готово

- Event Mirror (Фаза 4).
- Подключение очереди к Telegram/Memoh runtime.
- RAG, SLA, админка Studio, HTTP-маршруты очереди для внешних клиентов (по необходимости после Event Mirror).

## Последний стабильный commit

**Фаза 3 (Studio skeleton):** сообщение `feat(studio): phase 3 studio-api skeleton, compose, celery, alembic` — полный SHA см. `git rev-parse HEAD` на `pb-studio/main` (в репозитории один коммит фазы 3).

## Что изменилось в последней фазе

- Каркас API, инфраструктуры и фоновых процессов Studio; очередь ответов не интегрирована в HTTP/Celery бизнес-потоки (ожидает Event Mirror и ADR).

## Изменённые файлы (Фаза 3)

- `studio/**` (Dockerfile, `pb_studio/api`, `pb_studio/core`, `pb_studio/celery_app.py`, `pb_studio/worker`, `alembic/`, `tests/test_smoke_phase3.py`, `README.md`, `pyproject.toml` при необходимости)
- `docker-compose.local.yml`, `.env.example`
- `docs/03_IMPLEMENTATION_PLAN.md` (при ссылках), `docs/04_PROJECT_LOG.md`, `docs/05_CURRENT_TASK.md`, `docs/07_RUNBOOK_WINDOWS.md`, `docs/AI_CONTEXT.md`, `memory-bank/activeContext.md`, `memory-bank/progress.md`

## Принятые решения

- Очередь ответов как **источник истины по turn** живёт в Studio DB до интеграции с Memoh.
- Memoh и Telegram adapter **не менялись** в Фазе 3; Telegram runtime **не подключался**.
- Варианты интеграции A/B/C — в [`docs/06_DECISIONS.md`](docs/06_DECISIONS.md).

## Что нельзя трогать

- (как в Фазе 0.) Дополнительно до ADR: не патчить Memoh `telegram.go` / `inbound.go` без остановки и записи варианта в `docs/06_DECISIONS.md`.

## Следующая задача

- **Фаза 4: Event Mirror** — приём/нормализация событий из Memoh (или границы адаптера) в Studio, согласование с очередью и воркерами по плану; без расширения scope Фазы 3.

## Вопросы к GPT

- нет
