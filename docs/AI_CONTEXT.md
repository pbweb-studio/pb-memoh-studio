# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 6c (сводки — продуктовый API по чату)** — `summaries/product.py` + `POST /summaries/chat/{uuid}/today|yesterday|period`, `GET .../latest` под `STUDIO_ADMIN_TOKEN`; планировщик + шаблонная генерация (6b); периоды today/yesterday в UTC; без дубликатов для `generated`; `failed` за период → 409. Env `STUDIO_SUMMARY_*` проброшены в `studio-api` / `studio-worker` в `docker-compose.local.yml`. **Без** внешних LLM HTTP, **без** `sendMessage` для сводок. Memoh **не** менялся.

Фазы **6b**, **6a**, **5b**, **4b** — как ранее.

## Текущая цель

Фаза **6+** (LLM и/или доставка сводок в Telegram) — **не** начинать до отдельной постановки.

## Что уже работает

- Фазы 0–6c по Studio: см. `docs/04_PROJECT_LOG.md` и `docs/03_IMPLEMENTATION_PLAN.md`.
- **6c:** продуктовые эндпоинты сводок по `studio_chats.id`, идемпотентность и догенерация `pending`.
- **Проверка 4b:** зафиксирована в журнале; актуальные тесты Studio: `pytest tests/` (**75** кейсов после фазы 6c).

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
- Сводки 6a–6c: только Studio DB + шаблон; продуктовые маршруты 6c — см. `docs/06_DECISIONS.md` (фаза 6c); границы 6a–6b — там же.

## Следующая задача

- По постановке: фаза **6+** или другая фаза из плана.

## Вопросы к GPT

- нет
