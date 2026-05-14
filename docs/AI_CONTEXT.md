# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 5b (outbound system notifications)** — доставка `pending_for_control_group_delivery` / `failed_retryable` в Telegram **только** в активную control group: Bot API `sendMessage`, тот же `TELEGRAM_BOT_TOKEN`, без polling/webhook из Studio. Memoh **не** менялся.

Фазы **4b** (Memoh→Studio mirror, вариант C), **4a** (ingest), **5a** (модели/API/уведомления без send) — как ранее.

## Текущая цель

Фаза **6 (сводки)** — не начинать до отдельной постановки.

## Что уже работает

- Фазы 0–5b по Studio: см. `docs/04_PROJECT_LOG.md` и `docs/03_IMPLEMENTATION_PLAN.md`.
- **4b:** Memoh mirror (см. журнал и `internal/channel/adapters/telegram/*`).
- **5a:** `pb_studio/control_group/` — роли чатов, `studio_control_groups`, `studio_system_notifications`, интеграция после `my_chat_member`, админ-роуты, `STUDIO_ADMIN_TOKEN`.
- **5b:** `telegram_outbound`, `system_notification_delivery`, Alembic `004`, Celery `deliver_pending_system_notifications`, `GET/POST /notifications/system*`.
- **Проверка 4b:** зафиксирована в журнале; актуальные тесты Studio: `pytest tests/` (**48** кейсов после фазы 5b).

## Что ещё не готово

- Сводки (6), SLA (8), RAG, проекты, Studio Admin.

## Идентификаторы коммитов (история 4b)

- **Реализация Go-hook 4b:** `67bc573d1b5891f6cf9d3613580f59ca92200ec9`
- **Коммит записи проверки 4b в доках:** `1c8f9f6c0ef1ec71e78c3dcc92879c8c3b8c2b42`
- **Актуальный корень ветки:** `git rev-parse HEAD` на `pb-studio/main`.

**Код Event Mirror Studio (фаза 4a, якорь):** `eb0bdcd94699215118cd9aee41b5827453c21b7f`

**ADR (только текст):** `60a319773fc545be147a29625e3121613002bd7f`

## Файлы Memoh (фаза 4b)

См. предыдущую версию контекста: `telegram.go`, `studio_event_mirror.go`, `studio_event_mirror_test.go`.

## Принятые решения

- Один бот; системные Telegram-сообщения **не** в клиентские/проектные чаты; без control group — только БД / ожидание доставки.
- Outbound Studio: только `sendMessage` в control group; аудит и ретраи — см. `docs/06_DECISIONS.md` (фаза 5b).

## Следующая задача

- По постановке продукта: фаза **6** (сводки).

## Вопросы к GPT

- нет
