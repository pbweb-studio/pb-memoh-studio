# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 6d (сводки — доставка в control group)** — поля `delivery_*` на `studio_chat_summaries`, `summaries/summary_delivery.py`, `POST /summaries/{id}/deliver-control-group`, `POST /summaries/deliver-pending`, Celery `deliver_pending_chat_summaries`, env `STUDIO_SUMMARY_DELIVERY_*`. Отправка только в активную control group через `sendMessage` (тот же бот). **Без** Memoh, **без** LLM/RAG. Memoh **не** менялся.

Фазы **6c**, **6b**, **6a**, **5b**, **4b** — как ранее.

## Текущая цель

Фаза **6+** (LLM и/или расширенная продуктовая доставка) — **не** начинать до отдельной постановки.

## Что уже работает

- Фазы 0–6d по Studio: см. `docs/04_PROJECT_LOG.md` и `docs/03_IMPLEMENTATION_PLAN.md`.
- **6d:** доставка готовых сводок в Telegram control group с ретраями и аудитом.
- **Проверка 4b:** зафиксирована в журнале; актуальные тесты Studio: `pytest tests/` (**90** кейсов после фазы 6d).

## Что ещё не готово

- Внешний LLM, RAG, SLA, проекты, Studio Admin; прочие сценарии 6+.

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
- Сводки 6a–6d: Studio DB + шаблон + продуктовый API + доставка в control group — см. `docs/06_DECISIONS.md` (фазы 6a–6d).

## Следующая задача

- По постановке: фаза **6+** или другая фаза из плана.

## Вопросы к GPT

- нет
