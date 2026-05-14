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

## 2026-05-14 — Фаза 4b (Memoh → Studio Event Mirror, вариант C)

- Статус: завершена (минимальный транспорт); второй бот и внешний gateway **не** добавлялись; getUpdates/webhook **не** перенастраивались.
- Memoh: после дедупа `update_id` в `internal/channel/adapters/telegram/telegram.go` вызывается `mirrorTelegramUpdateToStudioAsync`; реализация в `internal/channel/adapters/telegram/studio_event_mirror.go`; тесты `studio_event_mirror_test.go`.
- Env: см. корневой `.env.example` (`STUDIO_EVENTS_URL`, `STUDIO_EVENTS_INGEST_TOKEN`, `MEMOH_STUDIO_EVENTS_TOKEN`, `MEMOH_TELEGRAM_EVENT_MIRROR_*`).
- Response Queue: только прежний флаг Studio `STUDIO_MIRROR_ENQUEUE_USER_MESSAGES`; Memoh его не трогает.

## 2026-05-14 — Проверка фазы 4b закрыта (Go + Studio + compose)

- Статус: автоматические проверки пройдены; код 4b **не** менялся.
- **Go:** `docker run --rm -v "<repo>:/src" -w /src golang:1.25 go test ./internal/channel/adapters/telegram/... -count=1` — **ok** (образ `golang:1.25` соответствует директиве `go 1.25.7` в `go.mod`).
- **Studio:** `docker run --rm -v "<repo>/studio:/app" -w /app python:3.12-slim bash -c "pip install -q -e '.[dev]' && pytest tests/ -v"` — **32 passed**.
- **Compose:** `docker compose -f docker-compose.local.yml config` — без ошибок.
- Запись о проверке вошла в коммит доков `1c8f9f6c0ef1ec71e78c3dcc92879c8c3b8c2b42` (см. `docs/AI_CONTEXT.md`); актуальный корень ветки: `git rev-parse HEAD`.

## 2026-05-14 — Фаза 5a (Studio: управляющая группа)

- Статус: реализовано в `studio/pb_studio/control_group/`, Alembic `003_control_group`, интеграция Event Mirror → `studio_system_notifications` для `my_chat_member`; исходящий Telegram и Memoh-send **не** делались.
- API: `GET /control-group`, `POST /control-group/set`, `GET /chats`, `GET /chats/unassigned`, `POST /chats/{uuid}/role`; опционально `STUDIO_ADMIN_TOKEN` (Bearer).
- Тесты: `pytest tests/` (включая `test_control_group.py`); `docker compose -f docker-compose.local.yml config` — ok.
- Полный SHA коммита: `git rev-parse HEAD`.

## 2026-05-14 — Фаза 5b (Studio: outbound system notifications → control group)

- Статус: исходящая доставка через Telegram Bot API `sendMessage` (`pb_studio/control_group/telegram_outbound.py`, `system_notification_delivery.py`); **тот же** `TELEGRAM_BOT_TOKEN`; **без** `getUpdates`/webhook из Studio; Memoh **не** менялся.
- Alembic `004_system_notification_delivery` (retry/last_error/delivered_at/updated_at, индекс по статусу).
- Celery: `deliver_pending_system_notifications`; API под `STUDIO_ADMIN_TOKEN`: `GET /notifications/system`, `POST /notifications/system/deliver-pending`.
- Env: `STUDIO_SYSTEM_NOTIFICATIONS_ENABLED`, `STUDIO_TELEGRAM_SEND_TIMEOUT_MS`, `STUDIO_SYSTEM_NOTIFICATION_MAX_RETRIES` (см. `.env.example`).
- Тесты: `pytest tests/` (включая `test_system_notification_delivery.py`); `docker compose -f docker-compose.local.yml config`.
- Полный SHA фиксирующего коммита: `git rev-parse HEAD` на `pb-studio/main`.

## 2026-05-14 — Фаза 5b: эксплуатационный хвост (compose)

- В `docker-compose.local.yml` для `studio-api` и `studio-worker` проброшены: `TELEGRAM_BOT_TOKEN`, `STUDIO_SYSTEM_NOTIFICATIONS_ENABLED`, `STUDIO_TELEGRAM_SEND_TIMEOUT_MS`, `STUDIO_SYSTEM_NOTIFICATION_MAX_RETRIES` (значения с хоста / `.env`; мигратор и beat без изменений).
- Проверки: `docker compose -f docker-compose.local.yml config`; `pytest tests/` в Docker.
- SHA: `git rev-parse HEAD` на `pb-studio/main`.

## 2026-05-14 — Фаза 6a (Studio: инфраструктура сводок без LLM)

- Таблица `studio_chat_summaries` (Alembic `005_chat_summaries`), пакет `pb_studio/summaries/`, планировщик + админ-API `GET/POST /summaries*`, Celery `plan_daily_chat_summaries` (только pending jobs).
- **Без** Memoh, **без** LLM, **без** Telegram outbound для сводок; Memoh и Go-код не менялись.
- Тесты: `pytest tests/` (включая `test_summaries_phase6a.py`); `docker compose -f docker-compose.local.yml config`.
- SHA: `git rev-parse HEAD` на `pb-studio/main`.

## 2026-05-14 — Фаза 6b (Studio: шаблонная генерация summary_text)

- `pb_studio/summaries/generator.py`, Celery `generate_pending_chat_summaries`, `POST /summaries/generate-pending`, `POST /summaries/{id}/generate`; env `STUDIO_SUMMARY_GENERATION_ENABLED`, `STUDIO_SUMMARY_MAX_SOURCE_MESSAGES`, `STUDIO_SUMMARY_MAX_BULLETS`.
- **Без** Memoh, **без** внешнего LLM API, **без** Telegram send для сводок.
- Тесты: `pytest tests/` (включая `test_summaries_phase6b.py`); `docker compose -f docker-compose.local.yml config`.
- SHA: `git rev-parse HEAD` на `pb-studio/main`.

## 2026-05-14 — Фаза 6c (Studio: продуктовый API сводок) + compose 6b

- Эндпоинты под `STUDIO_ADMIN_TOKEN`: `POST /summaries/chat/{uuid}/today`, `.../yesterday`, `.../period`, `GET .../latest`; логика в `pb_studio/summaries/product.py`; ответ `ChatSummaryProductOut`.
- В `docker-compose.local.yml` для `studio-api` и `studio-worker` проброшены `STUDIO_SUMMARY_GENERATION_ENABLED`, `STUDIO_SUMMARY_MAX_SOURCE_MESSAGES`, `STUDIO_SUMMARY_MAX_BULLETS`.
- **Без** Memoh, **без** внешнего LLM, **без** Telegram send для сводок, **без** RAG/SLA/проектов/Studio Admin.
- Тесты: `pytest tests/` (включая `test_summaries_phase6c.py`); `docker compose -f docker-compose.local.yml config`.
- SHA: `git rev-parse HEAD` на `pb-studio/main`.

## 2026-05-14 — Фаза 6d (Studio: доставка сводок в control group)

- Alembic `006_summary_delivery_control_group`: поля доставки на `studio_chat_summaries`; `pb_studio/summaries/summary_delivery.py`; `POST /summaries/{id}/deliver-control-group`, `POST /summaries/deliver-pending`, фильтр `GET /summaries?delivery_status=`; Celery `deliver_pending_chat_summaries`; env `STUDIO_SUMMARY_DELIVERY_ENABLED`, `STUDIO_SUMMARY_DELIVERY_MAX_RETRIES` в compose (api/worker); `telegram_send_message` — четвёртое значение `telegram_message_id`.
- **Без** Memoh, **без** LLM/RAG/SLA/проектов/Studio Admin; только `sendMessage` в активную control group (тот же бот).
- Тесты: `pytest tests/` (**90** passed в Docker); `docker compose -f docker-compose.local.yml config`; autouse-изоляция admin/env в `tests/conftest.py`.
- SHA: `git rev-parse HEAD` на `pb-studio/main`.

## 2026-05-14 — Фаза 7a (Studio: команды сводок из control group через Event Mirror)

- Таблица `studio_control_commands` (Alembic `007_studio_control_commands`); `pb_studio/control_commands/` (parser, service, schemas); `summaries/product.py` — опциональный `metadata_json` для команд; Celery `process_control_group_summary_commands`; API `GET /control-commands`, `POST /control-commands/process-pending` под `STUDIO_ADMIN_TOKEN`; env `STUDIO_CONTROL_COMMANDS_ENABLED`, `STUDIO_CONTROL_COMMANDS_MAX_BATCH` в `.env.example` и `docker-compose.local.yml` (studio-api, studio-worker).
- **Без** Memoh, **без** второго бота, **без** polling/webhook Studio, **без** LLM/RAG/SLA/проектов/Studio Admin UI; ответы только в активную control group.
- Тесты: `studio/tests/test_control_commands_phase7a.py`; полный `pytest tests/` в Docker; `docker compose -f docker-compose.local.yml config`.
- SHA: `git rev-parse HEAD` после фиксирующего коммита.

## 2026-05-14 — Фаза 7b (Studio: UX команд сводок + ACL в control group)

- Расширение `control_commands`: `/summary_chats`, `/summary_all_today`, `/summary_all_yesterday`, обновлённый help; ACL `STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS`; статус `failed_access_denied`, аудит `control_commands.access_denied`; агрегаты и списки с обрезкой; `GET /control-commands?command_name=`; `redact_secrets` в `last_error` при исключениях.
- **Без** Memoh, LLM/RAG/SLA/проектов/Studio Admin UI, второго бота, polling/webhook Studio.
- Тесты: `studio/tests/test_control_commands_phase7a.py`; `pytest tests/` в Docker; `docker compose -f docker-compose.local.yml config`.
- SHA: `git rev-parse HEAD` на ветке после коммита 7b (см. отчёт / CI).

## 2026-05-14 — Фаза 8a (Studio: SLA-инфра по чатам без LLM)

- Таблицы `studio_sla_policies`, `studio_sla_incidents` (Alembic `008_studio_sla`); `pb_studio/sla/` (detector, service, schemas); детектор по `studio_messages` для `client_chat` / `project_chat`; уведомления только в активную control group; Celery `detect_sla_incidents`; админ API `GET/POST /sla/*`; env `STUDIO_SLA_*` в `.env.example` и `docker-compose.local.yml` (studio-api, studio-worker).
- **Без** Memoh, второго бота, polling/webhook Studio, LLM/RAG/проектов/Studio Admin UI; не отправка в client/project/internal/service чаты.
- Тесты: `studio/tests/test_sla_phase8a.py`; полный `pytest tests/` в Docker; `docker compose -f docker-compose.local.yml config`.
- SHA: `git rev-parse HEAD` после коммита 8a (см. отчёт / CI).

## 2026-05-14 — Фаза 8b (Studio: SLA рабочие часы и mute)

- Alembic `009_studio_sla_working_hours` (поля policy: timezone, working_days/hours, holidays, mute); `sla/calendar.py` (`calculate_due_at`, блокировка mute); детектор и API `PATCH /sla/policies/{id}`, mute/unmute; env `STUDIO_SLA_DEFAULT_TIMEZONE`, `STUDIO_SLA_WORKING_HOURS_ENABLED`.
- **Без** Memoh, LLM/RAG/проектов/Studio Admin UI.
- Тесты: `tests/test_sla_calendar.py`, `tests/test_sla_phase8b.py`; `pytest tests/` в Docker; `docker compose -f docker-compose.local.yml config`.
- SHA: `git rev-parse HEAD` после коммита 8b (см. отчёт / CI).

## 2026-05-14 — Фаза 8c (Studio: SLA антиспам уведомлений в control group)

- Таблица `studio_sla_notification_events`, расширение `studio_sla_incidents` (Alembic `010_studio_sla_notification_events`); `sla/notifications.py`; детектор — батч уведомлений с digest и cooldown; env `STUDIO_SLA_NOTIFICATION_*`; API `GET /sla/notification-events`, `POST /sla/incidents/{id}/notify`, фильтры на `GET /sla/incidents`.
- **Без** Memoh, LLM/RAG/проектов/Studio Admin UI, второго бота, polling/webhook Studio.
- Тесты: `studio/tests/test_sla_phase8c.py`; полный `pytest tests/` в Docker (**156** passed); `docker compose -f docker-compose.local.yml config`.
- SHA: `795ce12b5cc5cf56aedfc9d08adcd3ab263887d9` (коммит 8c).

## 2026-05-14 — Фаза 9a (Studio: проекты и привязка чатов)

- Таблицы `studio_projects`, `studio_project_chats` (Alembic `011_studio_projects`); пакет `pb_studio/projects` (models/schemas/service/constants); API `/projects*` под `STUDIO_ADMIN_TOKEN`; команды `/project_create|list|bind|unbind|chats|help` из active control group (тот же scan/process, что и `/summary_*`); Celery-алиас `process_control_group_commands` → `run_control_commands_standalone`.
- **Без** Memoh, второго бота, polling/webhook Studio, LLM/RAG/дайджестов, Studio Admin UI; исходящие ответы команд — только в control group (`sendMessage`); не шлём в привязываемые чаты.
- Тесты: `studio/tests/test_projects_phase9a.py`; полный `pytest tests/` в Docker (**169** passed); `docker compose -f docker-compose.local.yml config`.
- SHA: `git rev-parse HEAD` на ветке после коммита 9a (фиксирующий коммит: `feat(studio): phase 9a projects and Telegram chat binding`).

## 2026-05-14 — Фаза 9b (Studio: project digest из chat summaries)

- Таблица `studio_project_digests` (Alembic `012_studio_project_digests`); пакет `pb_studio/project_digests`; генерация без LLM из привязанных чатов и `studio_chat_summaries`; API `/projects/{id}/digests*`, `/project-digests/*` под `STUDIO_ADMIN_TOKEN`; команды `/project_digest_today|yesterday|period|latest` + `/project_help`; Celery `generate_daily_project_digests`, `deliver_pending_project_digests`.
- **Без** Memoh, второго бота, polling/webhook Studio, LLM/RAG, Studio Admin UI; исходящие ответы и доставка дайджеста — только active control group (`sendMessage`); не шлём в client/project/internal/service чаты.
- Тесты: `studio/tests/test_project_digests_phase9b.py`; полный `pytest tests/` (**179** passed локально и в Docker); `docker compose -f docker-compose.local.yml config`.

## 2026-05-14 — Фаза 10a (Studio: knowledge base без embeddings)

- Таблицы `studio_knowledge_documents`, `studio_knowledge_document_versions`, `studio_knowledge_chunks` (Alembic `013_studio_knowledge_base`); пакет `pb_studio/knowledge`; API `/knowledge/*` при `STUDIO_KB_ENABLED` и `STUDIO_ADMIN_TOKEN`; команды `/kb_*` из control group; env `STUDIO_KB_CHUNK_*` и флаг в `docker-compose.local.yml`.
- **Без** Memoh, LLM/embeddings/RAG retrieval/Docling, Studio Admin UI, второго бота, polling/webhook Studio.
- Тесты: `studio/tests/test_knowledge_phase10a.py`; полный `pytest tests/` (**192** passed); `docker compose -f docker-compose.local.yml config`.
