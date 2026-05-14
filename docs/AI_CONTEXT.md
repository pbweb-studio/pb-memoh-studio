# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 4a завершена** — Event Mirror в Studio: `POST /events/telegram` (сырой JSON Telegram Update), дедуп по `update_id`, таблицы raw/chats/users/messages/lifecycle/audit, нормализация основных типов update. **Без** правок Memoh, **без** реального Telegram runtime, **без** исходящих сообщений в Telegram. Опциональный `QueueService.enqueue` только при явном флаге окружения (по умолчанию выкл.).

Дальше: **Фаза 4b+** — транспорт событий в ingest (после ADR A/B/C); **Фаза 5** — управляющая группа.

## Текущая цель

Согласовать и реализовать **доставку** апдейтов в Studio ingest (прокси, webhook, или минимальный контракт с Memoh) **без** самовольных правок `telegram.go` / `inbound.go`.

## Что уже работает

- Фазы 0–3: см. `docs/04_PROJECT_LOG.md`.
- **Фаза 4a:** [`studio/pb_studio/event_mirror/`](studio/pb_studio/event_mirror/), роутер `api/routes/events.py`, Alembic `001_initial` (DDL очереди) + `002_event_mirror`, тесты `tests/test_event_mirror.py`.

## Что ещё не готово

- Пайплайн Memoh/Telegram → Studio ingest.
- Управляющая группа, сводки, RAG, SLA, Studio Admin.

## Последний стабильный commit

Сообщение коммита Фазы 4a: `feat(studio): event mirror phase 4a ingest and tables` — полный SHA: `git rev-parse HEAD` на `pb-studio/main`.

## Что изменилось в последней фазе

- Приём и сохранение зеркала Telegram-формата в Postgres; контракт с Response Queue задокументирован и опционально включён флагом.

## Изменённые файлы (Фаза 4a)

- `studio/pb_studio/event_mirror/**`, `studio/pb_studio/api/**`, `studio/pb_studio/core/config.py`, `studio/pb_studio/core/database.py`, `studio/alembic/versions/**`, `studio/tests/test_event_mirror.py`
- `docs/03_IMPLEMENTATION_PLAN.md`, `docs/04_PROJECT_LOG.md`, `docs/05_CURRENT_TASK.md`, `docs/06_DECISIONS.md`, `docs/07_RUNBOOK_WINDOWS.md`, `docs/AI_CONTEXT.md`, `memory-bank/activeContext.md`, `memory-bank/progress.md`, `.env.example`

## Принятые решения

- Memoh и Telegram adapter **не менялись** в 4a.
- Исходящий Telegram API **не вызывается** из Event Mirror.
- Варианты A/B/C — `docs/06_DECISIONS.md`.

## Что нельзя трогать

- До ADR: не патчить Memoh `telegram.go` / `inbound.go` без записи в `docs/06_DECISIONS.md`.

## Следующая задача

- **4b+:** транспорт в ingest + выбор интеграции с Memoh.

## Вопросы к GPT

- нет
