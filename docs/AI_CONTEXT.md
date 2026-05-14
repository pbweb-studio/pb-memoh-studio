# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 11b (Studio: assistant rules → KB RAG)** — активные правила в user-prompt `ask_knowledge_base` (global + project при `project_id` + chat при `chat_id`); `POST /knowledge/ask` — `applied_rule_ids`, опциональный `chat_id`; `/kb_ask` использует `studio_chats.id` control group для chat-rules. **Без** Memoh и без применения правил к сводкам/SLA/digest.

Фазы **10g** (Telegram → KB), **10f** (HTTP KB), **10e** — см. журнал.

## Текущая цель

**6+** (LLM для сводок и пр.) или расширение **10+** (полный Docling pipeline, прочие KB UX) — по отдельной постановке.

## Что уже работает

- Фазы 0–11b по Studio: см. `docs/04_PROJECT_LOG.md` и `docs/03_IMPLEMENTATION_PLAN.md`.
- **11b:** те же правила — в KB RAG (`rag.py`, `/knowledge/ask`, `/kb_ask`): `applied_rule_ids`, опциональный `chat_id` в ask body.
- **11a:** правила ассистента в БД + audit, API `/assistant-rules*`, команды `/rule_*`.
- **10g:** импорт KB из Telegram document в control group (`/kb_import_last`, `/kb_import_file`), Bot API getFile+download, те же лимиты/Docling что 10f.
- **10f:** HTTP upload в KB, опциональный Docling, `/kb_import_help`.
- **10e:** RAG MVP по KB (`rag.py`, `/knowledge/ask`, `/kb_ask`).
- **10d:** OpenAI-compatible embeddings API + deterministic fallback.
- **10c:** pgvector / SQLite search, embed/search API, Celery.
- **10b:** staged import + parse pending, батч API и Celery, команды `/kb_parse` / `/kb_status`.
- **10a:** KB в БД, версии, чанки, HTTP API, команды `/kb_*` из control group.
- **9a–9b:** проекты, дайджесты, те же паттерны control group.
- **8a–8c:** SLA по зеркалу, календарь due, mute на policy, rate-limit и digest уведомлений, админ `/sla/*`.
- **Проверка 4b:** зафиксирована в журнале; актуальные тесты Studio: `pytest tests/` (**261** кейсов после фазы 11b, локально/Docker).

## Что ещё не готово

- Studio Admin; прочие сценарии 6+.

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
- **Фаза 10b:** parse pipeline для pending-версий; PDF/DOCX без Docling → `failed_unsupported`; см. `docs/06_DECISIONS.md`.
- **Фаза 10c:** эмбеддинги чанков + pgvector search в Postgres, fallback в SQLite; без LLM/chat; см. `docs/06_DECISIONS.md`.
- **Фаза 10d:** OpenAI-compatible `/embeddings` (httpx), батчи, redaction ключа в ошибках; deterministic для тестов; см. `docs/06_DECISIONS.md`.
- **Фаза 10e:** RAG MVP — `POST /knowledge/ask`, `/kb_ask`, retrieval только по KB chunks + один chat completion; см. `docs/06_DECISIONS.md`.
- **Фаза 10f:** HTTP multipart upload в KB, опциональный Docling для PDF/DOCX, `/kb_import_help`; см. `docs/06_DECISIONS.md`.
- **Фаза 11a:** assistant rules в Studio DB + audit + admin API + `/rule_*` из control group; см. `docs/06_DECISIONS.md`.
- **Фаза 11b:** assistant rules в user-prompt KB RAG + `applied_rule_ids`; см. `docs/06_DECISIONS.md`.

## Следующая задача

- По постановке: **6+** или расширение **10+** из плана.

## Вопросы к GPT

- нет
