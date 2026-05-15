# Журнал проекта

## 2026-05-15 — MVP v1: role-aware ассистент студии (PR1, один деплой)

- **Статус:** код в репо, тесты зелёные, деплой — следующий шаг оператора.
- **Контракт продукта:** новый файл `docs/FEATURES_v1.md` — продуктовое видение, поведение по 6 ролям чата (control_group / internal_chat / project_chat / client_chat / service_chat / unknown), MVP / LATER / WON'T фичи. Сменяет «кривой» `docs/03_IMPLEMENTATION_PLAN.md`.
- **9 новых MCP-инструментов Studio** в `studio/pb_studio/mcp_tools/extra_handlers.py`:
  - `studio_get_chat_context` — обязательный первый вызов в групповом чате (role, project, active_rules, can_respond_to_user).
  - `studio_smart_chat_report` — LLM-отчёт по содержимому чата (OpenAI-compatible через `STUDIO_KB_CHAT_*`).
  - `studio_assign_chat_role`, `studio_set_control_group` — управление ролями чатов.
  - `studio_create_project`, `studio_bind_chat_to_project` — проекты + автогенерация slug (включая транслит кириллицы).
  - `studio_get_active_rules`, `studio_disable_rule` — управление правилами ассистента.
  - `studio_get_recent_messages` — сырьё чата без LLM.
  - Регистрация — `studio/pb_studio/mcp_server/asgi.py` (теперь 20 MCP tools).
- **Skill `pb-studio-manager` v2:** `skills/pb-studio-manager/SKILL.md` переписан под единый мозг: правила поведения по `chat_role` (включая молчание в `client_chat` без ACL и `service_chat`), каталог всех 20 инструментов, UX-правила «один вопрос подряд», одна строка подтверждения после действий.
- **Удалён legacy Studio NL responder (необратимо):**
  - Стёртые файлы: `studio/pb_studio/nl/{processor,router,router_deterministic,gate_service,scan,triggers,turn_input,schemas,constants}.py`, `studio/pb_studio/api/routes/nl_gate.py`, 5 тестов `test_nl_*.py`.
  - Очистка env: `STUDIO_NL_*` и `STUDIO_MEMOH_GATE_TOKEN` удалены из `.env.example`, `.env.prod.example`, `docker-compose.prod.yml`, `studio/pb_studio/core/config.py`; `MEMOH_STUDIO_NL_GATE_*` удалены из `.env.example`.
  - Очистка кода: route `/integrations/memoh/nl-gate` снят (`pb_studio/api/main.py`); `verify_memoh_nl_gate_optional` / `verify_nl_gate_feature_enabled` удалены (`pb_studio/api/deps.py`); Celery `process_nl_interactions` удалён (`pb_studio/worker/tasks.py`); из `pb_studio/admin_ui/data.py` убран счётчик `nl_interactions`; в `/admin/nl-interactions` баннер сменён с «отключён» на «архивирован»; `pb_studio/nl/executor.py` очищен от ссылок на удалённые legacy функции, оставлены только утилиты для MCP-хендлеров (`_digest_all_chats`, `_list_chats_text`, `_kb_search_text`, `_diagnostics_text`, `_runtime_config_query_text`).
  - Оставлены как утилиты: `pb_studio/nl/executor.py` и `pb_studio/nl/models.py` (`StudioMemoryItem`, `StudioPlaybook` нужны MCP; `StudioNlInteraction` остаётся как архивная таблица — миграция/удаление — отдельной задачей).
- **Тесты:** `studio/tests/test_mcp_extra_handlers.py` — 22 теста (контекст / роли / control_group / проекты / правила / recent_messages / smart_report fallback / автогенерация slug). Прогон `pytest studio/tests/` — **320 passed**, 1 failed только `test_smoke_phase3.py::test_settings_load` из-за env (`REDIS_URL`) локального окружения — не регрессия.
- **Доки:** `docs/FEATURES_v1.md` (новый), `docs/AI_CONTEXT.md` (текущая фаза → MVP v1), `docs/05_CURRENT_TASK.md` (дорожная карта PR1 + PR2), `memory-bank/activeContext.md` (обновлён).
- **Деплой:** не выполнялся из этой сессии. Шаг оператора — pre-flight аудит VPS → один rollout → §11 в `docs/AI_CONTEXT.md`.

## 2026-05-15 — Single-brain: удалён Memoh NL gate, архив Studio NL responder

- **Статус:** код в репо — Memoh **`c1afe432`**: удалены `internal/studio/nl_gate*`, inbound без Studio consult, Telegram `stream.go` как upstream; Studio **`f22fd204`**: beat **никогда** не планирует `studio-process-nl-interactions`; `run_nl_interactions_standalone` / Celery task — no-op; Alembic **`018_nl_status_widen_finalize_pending`** (`status` VARCHAR(64), pending → **`ignored_disabled_single_brain_migration`**); pytest `test_nl_ux_regression` / `test_nl_turn_isolation` — **skip**.
- **Деплой:** оператор — образы + `alembic upgrade head` + §11 (`docs/AI_CONTEXT.md`).

## 2026-05-15 — Single-brain: NL off by default, Studio MCP, Memoh gate disable

- **Статус:** код в репо — флаги prod NL **false**, beat без NL-задачи при false, `nl-gate` **403** при false, Memoh **`MEMOH_STUDIO_NL_GATE_DISABLED`** + ранний skip в inbound, сервис **`studio-mcp`** в compose, 11 MCP tools, skill **`pb-studio-manager`**, тесты (`test_nl_phase` gate 403, celery schedule, `run_nl` skip, MCP bearer, Go `NLGateGloballyDisabled`), доки/runbook/ADR.
- **Скрипт:** `studio/scripts/migrate_nl_pending_to_ignored.sql` (опционально для старых pending).
- **Деплой:** не выполнялся из этой сессии.

## 2026-05-15 — NL Business & Learning Layer (Studio + Memoh)

- Статус: **код в репо** + **деплой на VPS 148.253.209.54** (2026-05-15, без переустановки Postgres/Redis volumes, без `set -x`, без печати `.env`/`config.toml` целиком).
- **VPS deploy (2026-05-15):** `git fetch` + `reset --hard` → **HEAD `16b80740`**; в `.env.prod` добавлены ключи **`STUDIO_NL_*`**, **`STUDIO_MEMOH_GATE_TOKEN`** (значение выровнено с существующим **`STUDIO_EVENTS_INGEST_TOKEN`** на хосте, без вывода); в `/opt/pb-studio/memoh/.env.memoh` — **`MEMOH_STUDIO_NL_GATE_URL`** (HTTPS `jar.pb-web.ru/.../nl-gate`) и **`MEMOH_STUDIO_NL_GATE_TOKEN`** (тот же ingest на стороне Memoh). `docker compose ... build` + `up` для **studio-migrate / api / worker / beat**; **Memoh `server`** пересобран и поднят. Миграция Alembic **`016 → 017_studio_nl_layer`** — exit 0.
- **Studio:** Alembic **`017_studio_nl_layer`** (`studio_nl_interactions`, `studio_memory_items`, `studio_playbooks`); пакет **`pb_studio/nl`** (router deterministic/OpenAI-compatible, triggers, executor, scan alias, processor, gate service); **`POST /integrations/memoh/nl-gate`**; Celery **`process_nl_interactions`** + beat interval **`STUDIO_NL_PROCESS_INTERVAL_SECONDS`**; админка **`/admin/nl-interactions`**, **`/admin/memory-items`**, **`/admin/playbooks`**; счётчики на dashboard.
- **Memoh:** **`internal/studio/nl_gate.go`**, вызов из inbound для Telegram group/supergroup до ассистента; env **`MEMOH_STUDIO_NL_GATE_URL`**, **`MEMOH_STUDIO_NL_GATE_TOKEN`** / **`MEMOH_STUDIO_EVENTS_TOKEN`**, **`MEMOH_STUDIO_NL_GATE_TIMEOUT_MS`**.
- **Тесты:** `studio/tests/test_nl_phase.py`; `internal/studio/nl_gate_test.go`. Полный прогон: `pytest studio/tests/ -q` (**302 passed** в Docker); `go test ./internal/studio/... -count=1`.
- Коммит: сообщение **`feat(studio): NL business layer with Memoh gate and admin UI`** (см. `git log -1 --oneline`).
- **Доки:** `docs/06_DECISIONS.md` (раздел NL), `docs/15_OPERATOR_GUIDE.md`, `docs/AI_CONTEXT.md`, memory-bank.

### §18 Ручная приёмка (NL, краткий чеклист)

1. **`STUDIO_NL_COMMANDS_ENABLED=false`:** mention в CG → отвечает **Memoh** (как раньше); Gate не подавляет.
2. **`STUDIO_NL_COMMANDS_ENABLED=true`**, Gate URL/token настроены: mention или reply-to-bot в CG, **не** slash Studio → **один** ответ из **Studio** (worker), Memoh **не** дублирует в том же сообщении.
3. Slash **`/summary_*`**, **`/kb_*`**, **`/project_*`**, **`/rule_*`** в CG → поведение **как до NL** (Memoh не блокируется gate для этих строк).
4. **Alias** `джарвис, …` / `jarvis, …` в CG (без mention) → обрабатывает Studio scan, Memoh молчит.
5. **ACL:** пользователь не из **`STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS`** (если список не пуст) → отказ NL, без утечек секретов в тексте ошибки.
6. **Админка:** открыть **`/admin/nl-interactions`**, фильтры status/mode/intent; memory/playbooks списки открываются.

### Автоматические проверки после выката (2026-05-15, VPS)

| Проверка | Результат |
|-----------|-----------|
| `curl` **Studio** `127.0.0.1:8000/health` | **200** |
| `curl` **https://jar.pb-web.ru/health** | **200** |
| `curl` **https://memo.pb-web.ru/health** | **200** |
| Контейнеры **pb-studio-prod-api/worker/beat**, **memoh-jar-server-1** | **Up**, api **healthy** |
| `getMe` | **ok**, username **jarvispbweb_bot** |
| `getWebhookInfo.url` | **null** (long poll) |
| `POST /integrations/memoh/nl-gate` с неверным Bearer | **HTTP 403** (маршрут жив, токены в ответе не печатались) |
| `bash deploy/scripts/vps-e2e-smoke.sh` | **PASS**, ожидаемые **SKIP** (history, **12_telegram**, pytest) |
| Логи Memoh по строке `nl-gate` в последних 200 строках | пусто (до первого живого mention) |

**Ручные шаги 7–10 (Telegram control group):** выполняет оператор по §18 выше — из этой сессии не верифицированы.

### 2026-05-15 — NL live-path: human replies, learning @mention, digest sanitize

- **Root cause (VPS по БД):** в `studio_nl_interactions.input_text` оставался префикс `@jarvispbweb_bot` при нестандартном пробеле после mention → `route_deterministic` не доходил до ветки «запомни» (fallback clarify). Сводки с `summary_id`/`tg=`/`UUID` — ветка `studio_nl_digest_debug` и/или устаревший образ worker относительно human-`list_chats`.
- **Исправления (Studio):** расширен `strip_leading_bot_mentions` (NBSP/кириллица сразу после username); learning по маркерам `запомни`/`…` через `find`, не только `startswith`; post-guard OpenAI-router при `clarify`+learning-cue; `format_nl_reply` для ряда intent не уходит в low-confidence clarify; список чатов «Вижу такие чаты» + control group + `•`; санитизация сниппетов digest; runtime model copy; pending: `?`/`@` и расширенные independent keywords.
- **Тесты:** `pytest tests/test_nl_ux_regression.py tests/test_nl_turn_isolation.py tests/test_nl_phase.py` (включая новые кейсы NBSP + digest sanitize).
- **Деплой:** только **studio-api / worker / beat** после merge; оператор повторяет 4 фразы приёмки (чаты / отчёт / запомни / модель).

- Статус: завершена.

### 2026-05-15 — NL anti–off-by-one: worker claim + gate fail-closed (VPS 148.253.209.54)

- **Цель:** убрать гонку Celery за одну `studio_nl_interactions` строку и второй ответ Memoh при сбое `PostNLGate`.
- **Репо:** `git fetch` + `reset --hard origin/pb-studio/main` → **HEAD `566052e1`**; **без** сноса Postgres/Redis volumes; **без** смены токенов; **без** `set -x` / печати `.env` / `config.toml` целиком.
- **Go test на VPS:** `go` не в PATH → **NOT_RUN** (сборка Memoh в Docker выполнила `go build` внутри Dockerfile).
- **Deploy Studio:** `docker compose --env-file .env.prod -f docker-compose.prod.yml build studio-api studio-worker studio-beat` + `up -d` → **PASS** (api **healthy**, worker/beat **Up**).
- **Deploy Memoh:** `MEMOH_ROOT=/opt/pb-studio/memoh docker compose -f deploy/docker-compose.memoh.yml build server` + `up -d server` → **PASS** (**memoh-jar-server-1** `healthy`).
- **Health / smoke:** `curl http://127.0.0.1:8000/health` → **200**; `https://jar.pb-web.ru/health` (GET) → **200**; `https://memo.pb-web.ru/` → **200**; `REPO=... BASE=... deploy/scripts/vps-e2e-smoke.sh` → **PASS**, ожидаемые **SKIP** (`10_history`, `12_telegram`, `14_pytest`).
- **Диагностика БД:** выполнен `studio/scripts/diag_last_nl_interactions.sql` через `docker exec -i pb-studio-prod-postgres psql ...` — последние строки на момент проверки относились к **предшествующему** живому прогону (в т.ч. clarify на «модель» при `@` в сохранённом `input_text`); **повторная** ручная приёмка **после** выката `566052e1` — оператор (4 фразы из § ниже).
- **Автоматика `/kb_help`:** не вызывалась из этой сессии (нет сценария без Telegram); оператор — в CG **`/kb_help`** и **`/kb_help@jarvispbweb_bot`**.
- **getMe / webhook / pending_update_count:** из SSH безопасно не извлекались (кавычинг с токеном); оператор: как в `docs/08_RUNBOOK_PRODUCTION.md` / предыдущие записи журнала (**long poll**, пустой webhook).
- **Код:** `studio/pb_studio/nl/processor.py`, `internal/studio/nl_gate.go`, `internal/channel/inbound/channel.go`, `studio/scripts/diag_last_nl_interactions.sql`, тесты `studio/tests/test_nl_ux_regression.py`; `docs/06_DECISIONS.md`, `docs/AI_CONTEXT.md`, memory-bank.

**Ручная приёмка после `566052e1` (control group, по порядку):**

1. `@jarvispbweb_bot какие чаты ты видишь?`
2. `@jarvispbweb_bot дай отчёт за сегодня`
3. `@jarvispbweb_bot запомни: не смешивай ответы между разными вопросами`
4. `@jarvispbweb_bot на какой модели ты работаешь?`

Затем: повторный `diag_last_nl_interactions.sql`, сверка `source_message_id` ↔ один `id`, `reply_text` ↔ `input_text` той же строки, логи worker на дубликаты `nl_reply_sent` для одного `source_message_id`.

**Статус:** автоматический деплой + smoke зафиксированы; **live** (4 фразы, `/kb_help`, getMe/webhook/pending) — **оператор**.

## 2026-05-14 — Фаза 0 (bootstrap)

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

## 2026-05-14 — Фаза 10b (Studio: KB parse pipeline)

- `pb_studio/knowledge/parsers.py`; pending-версии (`defer_parse` на `POST .../versions/text`); `POST /knowledge/documents/{id}/parse`, `POST /knowledge/parse-pending`; Celery `parse_pending_knowledge_documents`; команды `/kb_parse`, `/kb_status`.
- **Без** Memoh, LLM/embeddings/RAG retrieval, Studio Admin UI.
- Тесты: `studio/tests/test_knowledge_phase10b.py`; полный `pytest tests/` (**201** passed).

## 2026-05-14 — Фаза 10c (Studio: KB embeddings + pgvector search)

- Alembic `014_studio_knowledge_chunk_embeddings` (pgvector `vector(384)` в Postgres; JSON-список в SQLite для тестов); поля `embedding`, `embedding_model`, `embedded_at`, `embedding_status` (pending/embedded/failed), `embedding_last_error`; провайдер `deterministic` без внешнего API; `POST /knowledge/embed-pending`, `POST /knowledge/search`; Celery `embed_pending_knowledge_chunks`; `/kb_search` (+ `--project <slug>`) и `/kb_help`.
- **Без** Memoh, LLM chat/completion, генерации RAG-ответов, Studio Admin UI.
- Тесты: `studio/tests/test_knowledge_phase10c.py`; полный `pytest tests/` (**212** passed).

## 2026-05-14 — Фаза 10d (Studio: KB внешний embedding provider)

- `STUDIO_KB_EMBEDDING_PROVIDER` (`deterministic` | `openai_compatible`), `STUDIO_KB_EMBEDDING_API_BASE_URL`, `STUDIO_KB_EMBEDDING_API_KEY`, `STUDIO_KB_EMBEDDING_TIMEOUT_MS`, `STUDIO_KB_EMBEDDING_BATCH_SIZE`; httpx `POST …/embeddings`; redaction ключа в `embedding_last_error`; батч для openai-compatible не валит следующие батчи при ошибке.
- **Без** LLM chat, RAG-ответов, Memoh.
- Тесты: `studio/tests/test_knowledge_phase10d.py`; полный `pytest tests/` (**220** passed).

## 2026-05-14 — Фаза 10e (Studio: KB RAG question answering MVP)

- `STUDIO_KB_RAG_ENABLED`, `STUDIO_KB_CHAT_*`, `STUDIO_KB_RAG_TOP_K`, `STUDIO_KB_RAG_MAX_CONTEXT_CHARS`; модуль `pb_studio/knowledge/rag.py` (vector search → контекст → `POST …/chat/completions`); `POST /knowledge/ask` под `STUDIO_ADMIN_TOKEN`; `/kb_ask`, `/kb_help`; при пустом retrieval — фиксированный ответ «не найдено в базе знаний» без вызова LLM; redaction chat API key в ошибках control/API.
- **Без** Memoh, второго бота, polling/webhook Studio, Studio Admin UI; ответы `/kb_ask` только в active control group.
- Тесты: `studio/tests/test_knowledge_phase10e.py`; полный `pytest tests/` (**229** passed); `docker compose -f docker-compose.local.yml config`; `docker run` + `pytest tests/` (см. журнал проверок).

## 2026-05-14 — Фаза 10f (Studio: KB HTTP upload + Docling import)

- `POST /knowledge/documents/upload`, `POST /knowledge/documents/{id}/versions/upload` (multipart); `STUDIO_KB_DOCLING_ENABLED`, `STUDIO_KB_UPLOAD_MAX_BYTES`, `STUDIO_KB_ALLOWED_EXTENSIONS`, `STUDIO_KB_STORAGE_DIR`; модули `upload_io.py`, `docling_convert.py`; расширение `parsers.py` + сервис `ingest_*`; PDF/DOCX на диск и через Docling при доступности; иначе `failed_unsupported`; redacted `last_error`; `/kb_import_help`; compose volume `pb_studio_kb_uploads`; зависимость `python-multipart`.
- **Без** Memoh, Studio Admin UI, импорта файлов через Telegram-бота в этой фазе; логика RAG 10e не менялась.
- Тесты: `studio/tests/test_knowledge_phase10f.py`; полный `pytest tests/` (**238** passed); `docker compose -f docker-compose.local.yml config`; Docker `python:3.12-slim` + `pytest tests/`.

## 2026-05-14 — Фаза 10g (Studio: KB импорт из Telegram control group)

- `STUDIO_KB_TELEGRAM_IMPORT_ENABLED`, `STUDIO_KB_TELEGRAM_DOWNLOAD_TIMEOUT_MS`, `STUDIO_KB_TELEGRAM_MAX_FILE_BYTES` (0 = как upload max); `telegram_file_download.py`, `telegram_kb_import.py`; команды `/kb_import_last`, `/kb_import_file`; поиск последнего `document` в зеркале CG от того же user; скачивание → `ingest_new_document_from_upload` (как 10f); `_redact_kb_error_message` дополнен `redact_kb_import_error` (sk-).
- **Без** Memoh, второго бота, polling/webhook Studio, отдельного admin API для импорта; RAG 10e не менялся.
- Тесты: `studio/tests/test_knowledge_phase10g.py`; полный `pytest tests/` (**249** passed); `docker compose -f docker-compose.local.yml config`.

## 2026-05-14 — Фаза 12a (Studio: импорт Telegram Desktop JSON → Event Mirror)

- Пакет `pb_studio/history_import/`; таблица `studio_history_import_jobs`; миграция `016_studio_history_import_jobs`; `POST /history-import/telegram-json`, `GET /history-import/jobs`, `GET /history-import/jobs/{id}` при `STUDIO_HISTORY_IMPORT_ENABLED` + `STUDIO_ADMIN_TOKEN`; `STUDIO_HISTORY_IMPORT_MAX_BYTES`; запись в `studio_chats`, `studio_messages` (без `TelegramRawUpdate`), `studio_telegram_users`, lifecycle для `service`.
- **Без** Memoh, Telegram Bot API, polling/webhook Studio, LLM/RAG/embeddings, Studio Admin UI, исходящих сообщений в Telegram.
- Тесты: `studio/tests/test_history_import_phase12a.py`; полный `pytest tests/` (**268** passed).

## 2026-05-14 — Фаза 13a (Studio Admin UI skeleton)

- Пакет `pb_studio/admin_ui/` (Jinja2, Bootstrap 5 CDN, read-only страницы); `api/routes/admin_ui.py`: `GET /admin/`, разделы чатов / control group / сводок / проектов / SLA / KB / правил / history-import jobs; `GET/POST /admin/login`, `POST /admin/logout`; авторизация **`STUDIO_ADMIN_TOKEN`** (Bearer или cookie `studio_admin_session` через `itsdangerous`, секрет = токен; токен в логи не пишем); `GET /admin` → 302 на `/admin/`; статика `/admin/static`.
- **Без** Memoh, bot/polling/webhook, LLM/RAG, мутаций сущностей (кроме входа/выхода сессии).
- Тесты: `studio/tests/test_admin_ui_phase13a.py`; полный `pytest tests/` (**277** passed, Docker).

## 2026-05-14 — Фаза 13b (Studio Admin UI: детали + формы)

- Детальные GET под `/admin/*`; POST-формы вызывают существующие `control_group`, `projects`, `assistant_rules`, `sla`, `knowledge` services; flash `fs`/`fe`; шаблоны `*_detail.html`, списки проектов/KB/правил с карточками форм; `admin_ui/flash.py`.
- **Без** Memoh, бота, LLM/RAG, новых сущностей.
- Тесты: `studio/tests/test_admin_ui_phase13b.py`; полный `pytest tests/` (**283** passed, Docker).

## 2026-05-14 — Фаза 13c (Studio Admin UI: polish + usability)

- Пагинация (`pagination.py`), фильтры на списках (чаты / сводки / проекты / SLA / KB / правила), `formatting.py`, partials (`breadcrumbs`, `pagination_bar`, `filter_get_form`, `data_table`, `sidebar_nav`), offcanvas-навигация на узких экранах, `row_link_bases` для ссылок project/chat в таблицах.
- **Без** Memoh, бота, LLM/RAG, новых сущностей.
- Тесты: `studio/tests/test_admin_ui_phase13c.py`; полный `pytest tests/` (**289** passed, Docker).

## 2026-05-14 — Фаза 14a (Studio: production compose + runbook skeleton)

- `docker-compose.prod.yml`; `.env.prod.example`; `.gitignore` — `.env.prod`; `deploy/caddy/Caddyfile.example`, `deploy/scripts/backup-postgres.sh`, `deploy/BACKUP_RESTORE.md`; `docs/08_RUNBOOK_PRODUCTION.md`; ссылка из `docs/07_RUNBOOK_WINDOWS.md`.
- **Без** Memoh, фактического деплоя, реальных доменов/Caddy/TLS; логика приложения не менялась.
- Проверки: `docker compose -f docker-compose.prod.yml config`, `docker compose -f docker-compose.local.yml config` — ok; полный `pytest tests/` (**289** passed, Docker).

## 2026-05-14 — Фаза 14b (Studio: deploy readiness, без деплоя)

- `.env.prod.example` — REQUIRED/optional/secret, пустые секреты, комментарии к feature flags; `deploy/scripts/validate_env_prod.py`, `validate-env-prod.sh`, `smoke-prod.sh`, `restore-postgres.sh`, `backup-kb-volume.sh`; расширены `docs/08_RUNBOOK_PRODUCTION.md`, `deploy/BACKUP_RESTORE.md`, `deploy/caddy/Caddyfile.example`; `docs/07_RUNBOOK_WINDOWS.md`, `docs/03_IMPLEMENTATION_PLAN.md`, `docs/06_DECISIONS.md`.
- **Без** Memoh, логики приложения, реального деплоя, реальных доменов.
- Проверки: `docker compose -f docker-compose.prod.yml config`, `docker compose -f docker-compose.local.yml config` — ok; полный `pytest tests/` (**289** passed, Docker).

## 2026-05-14 — Фаза 14c (Studio: staging/prod deploy jar.pb-web.ru)

- VPS **148.253.209.54**, домен **https://jar.pb-web.ru** (Caddy → `127.0.0.1:8000`); stack `docker-compose.prod.yml`; `.env.prod` на сервере (**chmod 600**, в **`.gitignore`**, не в репозитории).
- Проверки: `GET /health`, `/admin/login`, `deploy/scripts/smoke-prod.sh`, `deploy/scripts/backup-postgres.sh` — ok.
- **Memoh не менялся.** Код на сервер — из локального дерева (`git archive`), т.к. `origin/pb-studio/main` отставал по `docker-compose.prod.yml`.
- Миграции: коммит **`f8dbd06e09f7b081733061ca1c6aefcf9b727afb`** — в `006_summary_delivery_control_group` расширение `alembic_version.version_num` до `VARCHAR(255)` (длинные revision id).
- **Security:** при одном прогоне вспомогательного shell с `set -x` значение `STUDIO_ADMIN_TOKEN` попало в лог; токен **ротирован** на VPS; правило: не использовать `bash -x` / `set -x` вокруг `export` секретов — см. `docs/08_RUNBOOK_PRODUCTION.md`, `docs/06_DECISIONS.md`. Файл **`/root/.studio_admin_token_once`** (если создавался): сохранить токен в менеджер секретов и **удалить** на сервере.

## 2026-05-14 — Фаза 11b (Studio: assistant rules → KB RAG prompt)

- `list_active_rules_for_kb_rag` в `assistant_rules/service.py`; `rag.py` — блок «Инструкции Studio» **перед** фрагментами в user message; `KnowledgeAskOut.applied_rule_ids`; тело `POST /knowledge/ask` — опциональный `chat_id`; `/kb_ask` передаёт `control_group_chat_id` как контекст чата для chat-scope правил.
- **Только** Studio KB RAG (OpenAI-compatible chat completion 10e); **без** Memoh, сводок, SLA, project digest, Studio Admin UI.
- Тесты: блок в `studio/tests/test_knowledge_phase10e.py` (фаза 11b); полный `pytest tests/` (**261** passed).

## 2026-05-14 — Фаза 11a (Studio: assistant rules — storage, API, control commands)

- Таблицы `studio_assistant_rules`, `studio_assistant_rule_audit`; миграция `015_studio_assistant_rules`; пакет `pb_studio/assistant_rules/`; API `/assistant-rules` (листинг, создание, `GET/{id}`, `PATCH`, `POST …/disable`, `GET /assistant-rules/audit`) под `STUDIO_ADMIN_TOKEN`; команды `/rule_*` в control group (скан `/rule`); аудит `created` / `updated` / `disabled`.
- **Без** Memoh, без Studio Admin UI; применение правил к KB RAG — **фаза 11b** (см. запись 11b выше).
- Тесты: `studio/tests/test_assistant_rules_phase11a.py`; полный `pytest tests/` (**256** passed).

## 2026-05-14 — VPS E2E smoke + синхронизация checkout с origin

- Добавлены и закоммичены в **`origin/pb-studio/main`**: `deploy/scripts/vps-e2e-smoke.py`, `deploy/scripts/vps-e2e-smoke.sh` (без `set -x`; slug под `ProjectCreate.pattern`; проверка **302** на `/admin/chats` без auth через `curl` без следования редиректам; блок **14** — SKIP, если в prod-образе нет модуля pytest).
- На VPS **148.253.209.54**: `git fetch` + **`git reset --hard origin/pb-studio/main`** (несохранённые правки **tracked**-файлов на сервере сброшены; **`.env.prod`** вне git — сохраняется), повторный **`./deploy/scripts/vps-e2e-smoke.sh`** — **PASS** с ожидаемыми **SKIP** (RAG / Telegram / history import / pytest в образе).
- **Memoh не менялся.** Значения секретов в журнал не заносятся.

## 2026-05-14 — MVP стабилизация (роли, команды, Memoh группы)

- **Коммит:** **`e6e4a13f`** (`fix(mvp): stabilize Memoh group replies, Studio control commands beat, docs`).
- **Документация:** добавлен `docs/15_OPERATOR_GUIDE.md`; обновлены `docs/AI_CONTEXT.md`, `docs/06_DECISIONS.md`, memory-bank.
- **Memoh:** режим «final only» для group/supergroup по умолчанию (`MEMOH_TELEGRAM_GROUP_STREAMING_ENABLED`); правки в `internal/channel/adapters/telegram/stream.go`, `telegram.go`, тесты `stream_test.go`; исправление long poll / redaction URL в логах — коммит **`b0e7b510`**.
- **Studio Admin:** подсказка Memoh vs Studio на dashboard и control group; страница **`/admin/control-commands`** (последние `studio_control_commands`, кнопка process-pending).
- **Studio:** парсер slash-команд с `@botusername`; `/kb_help` и unknown-подсказка не блокируются выключенным `STUDIO_KB_ENABLED`; Celery **beat_schedule** на `process_control_group_commands`; настройка **`STUDIO_CONTROL_COMMANDS_INTERVAL_SECONDS`** (дефолт 5).
- **Тесты:** расширены `test_control_commands_phase7a.py`, `test_knowledge_phase10a.py`.
- **Security:** если полный **TELEGRAM_BOT_TOKEN** попадал в логи (в т.ч. через URL Bot API) — рекомендуется ротация; статус фиксируется в `docs/AI_CONTEXT.md`. **2026-05-14:** оператор зафиксировал **отказ от ротации** текущего токена (согласованный остаточный риск).

## 2026-05-15 — VPS: выборочный деплой MVP + фикс Celery worker

- **Сервер:** **148.253.209.54**, **`/opt/pb-studio/pb-memoh-studio`**, **`git reset --hard origin/pb-studio/main`** → **HEAD `7a4a8a106974b4ce1a67bd3677bef280048e54d3`**.
- **Сервисы:** Memoh **`deploy/docker-compose.memoh.yml`** — **build/up `server`**; Studio **`docker-compose.prod.yml`** — **build/up `studio-api` `studio-worker` `studio-beat`**; Postgres/Redis **без** пересоздания volumes.
- **Проверки:** Studio **`/health`**; Memoh web **`:8082/health`**; Telegram **getMe** / **getWebhookInfo** (без печати токена) — **jarvispbweb_bot**, webhook пустой, **pending_update_count=0**; **`GET /control-group`** — active, **Управление Jarvis**, **-1003903704506**; в БД **485395885** → `chat_role=unknown` (не control group).
- **Celery:** после выката **`e6e4a13f`** worker ловил **`RuntimeError: ... different loop`** на `process_control_group_commands`; исправление **`7a4a8a10`** — **`dispose_engine()`** в `finally` у **`run_control_commands_standalone`**; **vps-e2e-smoke** — логи worker снова **PASS**.
- **Smoke:** на момент этого выката оставался **FAIL** на **`/admin/assistant-rules`** (HTTP **500**); **исправлено** коммитом **`8af1537d`** (см. раздел ниже). **SKIP** — history import, блок **12** live Telegram, pytest в образе.
- **Ручная приёмка Telegram:** **2026-05-14** — оператор подтвердил личку **`mvp-private-001`**, **`/kb_help`** и **`/kb_help@jarvispbweb_bot`** в control group (скрины). Утром **2026-05-15** в SQL не фиксировались **`mvp-group-mention-001`** / **`mvp-private-001`** в `studio_messages`; позже **`mvp-group-mention-001`** появился в зеркале — см. раздел «assistant-rules» ниже. **`/kb_help@...`** в `studio_control_commands` на утренней выборке — **0 строк**.
- **Security `TELEGRAM_BOT_TOKEN`:** **2026-05-14** — оператор **без ротации** (согласовано, остаточный риск принят); см. `docs/AI_CONTEXT.md`.

## 2026-05-15 — Studio Admin `GET /admin/assistant-rules`: устранение HTTP 500, smoke PASS

- **Причина:** в `studio/pb_studio/api/routes/admin_ui.py` в **`admin_assistant_rules`** / **`admin_assistant_rule_create_post`** использовались **`AssistantRuleScope`**, **`AssistantRuleStatus`**, **`AssistantRuleCreate`**, **`rules_service`** без импортов → **`NameError`** → ответ **500** в prod.
- **Исправление:** коммит **`8af1537d`** (`fix(studio-admin): restore missing imports for assistant-rules admin page`) — импорты из `pb_studio.assistant_rules.*`. Локально: **`pytest`** `tests/test_admin_ui_phase13a.py::test_admin_section_pages_200_with_bearer`, `tests/test_admin_ui_phase13c.py` — **PASS**.
- **VPS 148.253.209.54:** `git fetch` + **`git reset --hard origin/pb-studio/main`** → **HEAD `8af1537d`**; **`docker compose --env-file .env.prod -f docker-compose.prod.yml build/up`** только **`studio-api`**, **`studio-worker`**, **`studio-beat`**; Memoh **не** пересобирался.
- **`REPO=... BASE=https://jar.pb-web.ru bash ./deploy/scripts/vps-e2e-smoke.sh`:** **PASS**; **`4_admin_/admin/assistant-rules`** и **`4_filter_...assistant-rules?status=active`** — **200**. Ожидаемые **SKIP** без изменений: history import, **12_telegram**, **14_pytest**.
- **Зеркало:** в **`studio_messages`** на момент проверки — **≥1** строка, содержащая **`mvp-group-mention-001`** (текст дошёл до Event Mirror). UX в Telegram (один ответ бота, без дублей / «……») — приёмка оператором при необходимости.

