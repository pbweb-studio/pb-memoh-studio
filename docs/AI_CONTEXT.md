# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 7b (UX команд сводок + ACL в control group)** — поверх 7a: `/summary_chats`, `/summary_all_today`, `/summary_all_yesterday`, обновлённый help; список чатов и агрегаты с обрезкой под лимит Telegram; ACL `STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS` (пусто = все); статус `failed_access_denied` + отказ в control group + аудит; `GET /control-commands?command_name=`; `redact_secrets` для `last_error`. **Без** Memoh, **без** второго бота и polling/webhook Studio, **без** LLM/RAG. Memoh **не** менялся.

Фазы **6d**, **6c**, **6b**, **6a**, **5b**, **4b** — как ранее.

## Текущая цель

Фаза **6+** (LLM и/или расширенная продуктовая доставка) или полная **фаза 7** по плану — **не** начинать до отдельной постановки.

## Что уже работает

- Фазы 0–7b по Studio: см. `docs/04_PROJECT_LOG.md` и `docs/03_IMPLEMENTATION_PLAN.md`.
- **7a–7b:** команды сводок из control group по зеркалу (в т.ч. список чатов и all-day агрегаты), ACL по Telegram user id, админ API + Celery.
- **Проверка 4b:** зафиксирована в журнале; актуальные тесты Studio: `pytest tests/` (**116** кейсов после фазы 7b, Docker).

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
- Фазы **7a–7b:** команды `/summary_*` только из зеркала control group → ответы только в control group; ACL по `STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS`; см. `docs/06_DECISIONS.md` (фазы 7a, 7b).

## Следующая задача

- По постановке: фаза **7** (полный scope плана) или **6+** / другая фаза из плана.

## Вопросы к GPT

- нет
