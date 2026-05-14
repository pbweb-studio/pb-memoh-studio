# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 5a (управляющая группа в Studio)** — модели, API, записи системных уведомлений из Event Mirror (`my_chat_member`), политика доставки только в control group. **Исходящий Telegram** (реальная отправка в группу) **не** реализован; Memoh **не** менялся.

Фазы **4b** (Memoh→Studio mirror, вариант C) и **4a** (ingest) остаются как ранее.

## Текущая цель

Фаза **6 (сводки)** — не начинать до отдельной постановки. Опционально: исходящая доставка system notifications в Telegram control group (worker/Memoh) — только после ADR при необходимости hook в Memoh.

## Что уже работает

- Фазы 0–5a по Studio: см. `docs/04_PROJECT_LOG.md` и `docs/03_IMPLEMENTATION_PLAN.md`.
- **4b:** Memoh mirror (см. предыдущие записи журнала и `internal/channel/adapters/telegram/*`).
- **5a:** `pb_studio/control_group/` — роли чатов, `studio_control_groups`, `studio_system_notifications`, интеграция после `my_chat_member`, админ-роуты, `STUDIO_ADMIN_TOKEN`.
- **Проверка 4b:** зафиксирована в журнале; актуальные тесты Studio: `pytest tests/` (**41** тест-кейс после фазы 5).

## Что ещё не готово

- Исходящая отправка системных уведомлений в Telegram (только в control group) — не в 5a.
- Сводки (6), SLA (8), RAG, проекты, Studio Admin.

## Идентификаторы коммитов (история 4b)

- **Реализация Go-hook 4b:** `67bc573d1b5891f6cf9d3613580f59ca92200ec9`
- **Коммит записи проверки 4b в доках:** `1c8f9f6c0ef1ec71e78c3dcc92879c8c3b8c2b42`
- **Актуальный корень ветки:** `git rev-parse HEAD`

**Код Event Mirror Studio (фаза 4a, якорь):** `eb0bdcd94699215118cd9aee41b5827453c21b7f`

**ADR (только текст):** `60a319773fc545be147a29625e3121613002bd7f`

## Файлы Memoh (фаза 4b)

См. предыдущую версию контекста: `telegram.go`, `studio_event_mirror.go`, `studio_event_mirror_test.go`.

## Принятые решения

- Один бот; системные Telegram-сообщения **не** в клиентские/проектные чаты; без control group — только БД.
- Фаза 5a без Memoh-send; новый Memoh hook только после записи в `docs/06_DECISIONS.md` (при необходимости).

## Следующая задача

- По решению продукта: доставка `pending_for_control_group_delivery` в Telegram **или** фаза 6.

## Вопросы к GPT

- нет
