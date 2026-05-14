# Журнал проекта

## 2026-05-14 — Фаза 0 (Bootstrap)

- Статус: завершена.
- Клонирован upstream Memoh; remotes: `upstream` = memohai/Memoh, `origin` = pbweb-studio/pb-memoh-studio; ветка `pb-studio/main`; тег `stable-upstream-memoh`.
- Добавлены каркас `studio/`, документация `docs/`, Memory Bank, Cursor Rules, `.env.example`, `.cursorignore`, `docker-compose.local.yml` (Postgres16+pgvector, Redis), скелет `docker-compose.prod.yml`.
- Продуктовая логика Memoh не менялась.
- Стабильный коммит фазы 0: ветка `pb-studio/main`, сообщение `chore(repo): bootstrap studio scaffold and docs` (hash: `git rev-parse HEAD`).

## 2026-05-14 — Фаза 1 (разведка Memoh)

- Статус: завершена; код Memoh не изменялся.
- Задокументированы: Telegram adapter (`internal/channel/adapters/telegram/telegram.go`), inbound через `internal/channel/inbound.go` (очередь + воркеры) → `internal/channel/inbound/channel.go` (`HandleInbound`, `RouteDispatcher`, `sendModeConfirmation` / 👀), MCP (`internal/mcp`, `internal/workspace`, `internal/agent/tools`).
- Варианты Response Queue: [`docs/06_DECISIONS.md`](docs/06_DECISIONS.md). Детали трассировки: [`docs/03_IMPLEMENTATION_PLAN.md`](docs/03_IMPLEMENTATION_PLAN.md).
- Коммит: `4a42646617a7f632b9fc8d5c84e57dd45026052d`.

## 2026-05-14 — Фаза 2a (Response Queue в Studio)

- Статус: завершена (безопасная часть); Memoh / Telegram не менялись.
- Добавлены `studio/pb_studio/response_queue` (SQLAlchemy модели, `QueueService`, Pydantic-контракт, pytest), `studio/migrations/001_response_queue.sql`, обновлены `docs/*`, memory-bank.
- Коммит: `c4e382c22553f3b7b4fc5b2d46fec50240c3ea82`.

## 2026-05-14 — Фаза 3 (Studio Layer skeleton)

- Статус: завершена; Memoh / Telegram adapter / Telegram runtime **не** менялись и **не** подключались.
- Добавлены: FastAPI `studio-api` (`GET /health`), Pydantic Settings, async SQLAlchemy session layer, Redis client, Alembic (`studio/alembic`), Celery app + skeleton worker/beat, `studio/Dockerfile`, обновлён `docker-compose.local.yml` (postgres, redis, migrate, studio-api, studio-worker, studio-beat), smoke-тесты Фазы 3.
- Event Mirror, RAG, SLA, проекты, Studio Admin — **вне** scope Фазы 3.
- Response Queue (`QueueService`) — только как внутренний модуль; интеграция с Event Mirror — Фаза 4.
- Коммит: сообщение `feat(studio): phase 3 studio-api skeleton, compose, celery, alembic` (SHA — `git rev-parse HEAD` на `pb-studio/main`).

## 2026-05-14 — Фаза 4a (Event Mirror в Studio, без Memoh)

- Статус: завершена; Memoh / Telegram adapter / реальный Telegram runtime **не** менялись; **нет** исходящих запросов к Telegram API.
- Добавлены: `POST /events/telegram`, модели `studio_telegram_raw_updates`, `studio_chats`, `studio_telegram_users`, `studio_messages`, `studio_chat_lifecycle_events`, `studio_audit_log`, сервис нормализации, Alembic `002_event_mirror`, переписан `001_initial` на явный DDL очереди; опционально `STUDIO_MIRROR_ENQUEUE_USER_MESSAGES` → `QueueService.enqueue`; опциональный `STUDIO_EVENTS_INGEST_TOKEN`.
- Тесты: `studio/tests/test_event_mirror.py`.
- Коммит: сообщение `feat(studio): event mirror phase 4a ingest and tables` (SHA — `git rev-parse HEAD` на `pb-studio/main`).

## 2026-05-14 — ADR: интеграция Telegram/Memoh → Studio Event Mirror (перед 4b)

- Статус: зафиксировано **только в документации**; код Memoh и Telegram adapter **не** менялись; транспорт **4b не** реализован.
- Добавлено: раздел **ADR** в `docs/06_DECISIONS.md` (таблица A/B/C: файлы, путь в `POST /events/telegram`, риски, откат, тесты; рекомендация **C**); краткая отсылка в `docs/03_IMPLEMENTATION_PLAN.md`; обновлены `docs/AI_CONTEXT.md`, `docs/05_CURRENT_TASK.md`, `memory-bank/*`, `docs/04_PROJECT_LOG.md`.
- Полный SHA снимка с телом ADR: см. `docs/AI_CONTEXT.md` (40-символьный SHA после фиксирующего коммита на `pb-studio/main`).
