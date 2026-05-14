# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 10a (Studio: knowledge base без embeddings)** — таблицы `studio_knowledge_documents`, `studio_knowledge_document_versions`, `studio_knowledge_chunks` (Alembic `013_studio_knowledge_base`); пакет `pb_studio/knowledge`; админ-API `/knowledge/*` при `STUDIO_KB_ENABLED` и `STUDIO_ADMIN_TOKEN`; команды `/kb_help`, `/kb_list`, `/kb_get`, `/kb_add` из active control group (Event Mirror + ACL `STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS`); детерминированный splitter `STUDIO_KB_CHUNK_*`. **Без** Memoh, второго бота, polling/webhook Studio, LLM/embeddings/RAG retrieval/Docling, Studio Admin UI; не шлём в client/project/internal/service чаты.

Фазы **9b**, **9a**, **8a–8c**, **7b**–**4b** — см. журнал.

## Текущая цель

**6+** (LLM/продуктовая доставка сводок) или **10+** (Docling, embeddings, pgvector, поиск) — только по отдельной постановке.

## Что уже работает

- Фазы 0–10a по Studio: см. `docs/04_PROJECT_LOG.md` и `docs/03_IMPLEMENTATION_PLAN.md`.
- **10a:** KB в БД, версии из текста, чанки, HTTP API, команды `/kb_*` из control group.
- **9a–9b:** проекты, дайджесты, те же паттерны control group.
- **8a–8c:** SLA по зеркалу, календарь due, mute на policy, rate-limit и digest уведомлений, админ `/sla/*`.
- **Проверка 4b:** зафиксирована в журнале; актуальные тесты Studio: `pytest tests/` (**192** кейса после фазы 10a, локально/Docker).

## Что ещё не готово

- Внешний LLM, embeddings, RAG retrieval, Studio Admin; прочие сценарии 6+.

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
- **Фазы 8a–8c:** SLA first response по зеркалу; календарь и mute на policy; уведомления SLA только в control group; см. `docs/06_DECISIONS.md` (фазы 8a–8c).
- **Фаза 9a:** проекты и bind чатов только в Studio DB; команды `/project_*` — те же правила доставки и ACL, что `/summary_*`; см. `docs/06_DECISIONS.md`.
- **Фаза 9b:** project digest из summaries, только Studio DB + шаблон; доставка и команды — только control group; см. `docs/06_DECISIONS.md`.
- **Фаза 10a:** KB — только Studio DB + детерминированные чанки; API при флаге `STUDIO_KB_ENABLED`; команды `/kb_*` — только control group; см. `docs/06_DECISIONS.md`.

## Следующая задача

- По постановке: **6+** или **10+** (Docling/embeddings/RAG) из плана.

## Вопросы к GPT

- нет
