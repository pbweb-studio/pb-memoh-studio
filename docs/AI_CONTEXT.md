# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 6a (сводки — инфраструктура)** — таблица `studio_chat_summaries`, планировщик pending jobs из Event Mirror (`studio_messages` + `studio_chat_lifecycle_events` в периоде), админ-роуты `GET /summaries`, `POST /summaries/plan`, `GET /summaries/{id}`, Celery `plan_daily_chat_summaries`. **Без** LLM, **без** генерации текста, **без** отправки сводок в Telegram. Memoh **не** менялся.

Фазы **4b**, **4a**, **5a**, **5b** — как ранее.

## Текущая цель

Полноценная фаза **6+** (генерация/UX сводок) — **не** начинать до отдельной постановки.

## Что уже работает

- Фазы 0–6a по Studio: см. `docs/04_PROJECT_LOG.md` и `docs/03_IMPLEMENTATION_PLAN.md`.
- **6a:** `pb_studio/summaries/`, Alembic `005`, Celery `plan_daily_chat_summaries`, админ-API сводок.
- **Проверка 4b:** зафиксирована в журнале; актуальные тесты Studio: `pytest tests/` (**56** кейсов после фазы 6a).

## Что ещё не готово

- Генерация текста сводок (LLM), отправка сводок в Telegram, продукт «сводка сегодня»; фаза 7+; SLA (8), RAG, проекты, Studio Admin.

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
- Сводки 6a: только Studio DB + планировщик; границы — см. `docs/06_DECISIONS.md` (фаза 6a).

## Следующая задача

- По постановке: фаза **6+** или другая фаза из плана.

## Вопросы к GPT

- нет
