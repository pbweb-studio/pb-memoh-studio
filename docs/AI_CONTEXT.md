# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 6b (сводки — шаблонная генерация текста)** — `summaries/generator.py`: pending → `summary_text` из `studio_messages` / `studio_chat_lifecycle_events` (детерминированный шаблон); Celery `generate_pending_chat_summaries`; `POST /summaries/generate-pending`, `POST /summaries/{id}/generate`; env `STUDIO_SUMMARY_*`. **Без** внешних LLM HTTP, **без** `sendMessage` для сводок. Memoh **не** менялся.

Фазы **6a**, **5b**, **4b** — как ранее.

## Текущая цель

Фаза **6+** (LLM / продукт / доставка сводок) — **не** начинать до отдельной постановки.

## Что уже работает

- Фазы 0–6b по Studio: см. `docs/04_PROJECT_LOG.md` и `docs/03_IMPLEMENTATION_PLAN.md`.
- **6b:** шаблонная генерация сводок, батч с изоляцией ошибок, админ-эндпоинты генерации.
- **Проверка 4b:** зафиксирована в журнале; актуальные тесты Studio: `pytest tests/` (**66** кейсов после фазы 6b).

## Что ещё не готово

- Внешний LLM, RAG, отправка сводок в Telegram, продуктовые сценарии 6+; SLA (8), проекты, Studio Admin.

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
- Сводки 6a–6b: только Studio DB + шаблон; границы — см. `docs/06_DECISIONS.md` (фазы 6a, 6b).

## Следующая задача

- По постановке: фаза **6+** или другая фаза из плана.

## Вопросы к GPT

- нет
