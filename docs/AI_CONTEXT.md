# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 8a (SLA-инфра по чатам без LLM)** — таблицы `studio_sla_policies`, `studio_sla_incidents` (Alembic `008_studio_sla`); детектор по `studio_messages` для `client_chat` / `project_chat` (последнее пользовательское входящее без ответа бота + просрочка first response); уведомления только в активную control group при включённом флаге; Celery `detect_sla_incidents`; админ API `GET/POST /sla/*`; env `STUDIO_SLA_*`. **Без** Memoh, **без** второго бота и polling/webhook Studio, **без** LLM/RAG. Memoh **не** менялся.

Фазы **7b**, **7a**, **6d**–**4b** — как ранее в журнале.

## Текущая цель

Полная **фаза 8** (рабочие часы, антиспам, mute и т.д.) или **6+** / **7** — только по отдельной постановке.

## Что уже работает

- Фазы 0–8a по Studio: см. `docs/04_PROJECT_LOG.md` и `docs/03_IMPLEMENTATION_PLAN.md`.
- **8a:** SLA first-response по зеркалу, инциденты в БД, policies, ack/resolve, доставка уведомлений только в control group.
- **Проверка 4b:** зафиксирована в журнале; актуальные тесты Studio: `pytest tests/` (**130** кейсов после фазы 8a, Docker).

## Что ещё не готово

- Внешний LLM, RAG, расширенный SLA (фаза 8 целиком), проекты, Studio Admin; прочие сценарии 6+.

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
- **Фаза 8a:** SLA first response по зеркалу; уведомления SLA только в control group; см. `docs/06_DECISIONS.md` (фаза 8a).

## Следующая задача

- По постановке: расширение **фазы 8** или **6+** / **7** из плана.

## Вопросы к GPT

- нет
