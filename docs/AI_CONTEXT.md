# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Single-brain Memoh + Studio MCP (май 2026)** — второй ответчик Studio NL **архивирован**: Memoh **без** `PostNLGate` / `internal/studio`; Celery beat **без** `studio-process-nl-interactions`; `run_nl_interactions_standalone` — no-op; Alembic **`018`** финализирует старые `pending`. Бизнес для ассистента: **`studio-mcp`** (Bearer **`STUDIO_MCP_AUTH_TOKEN`**), инструменты `studio_*`, skill **`pb-studio-manager`**. Event Mirror — пассивный ingest; slash/control — legacy/operator (см. ADR). Коммиты: **`c1afe432`** (Memoh), **`f22fd204`** (Studio).

### §11 Ручная приёмка (Telegram, после выката single-brain)

1. В CG: mention бота — **один** ответ **Memoh** (Studio NL не вмешивается).
2. В Memoh Admin: MCP **tools/list** видит `studio_list_chats` и остальные `studio_*`.
3. Вызов инструмента (например список чатов) возвращает осмысленный текст без утечки секретов в ошибках.
4. **`/admin/nl-interactions`** — баннер «NL responder отключён» при `STUDIO_NL_COMMANDS_ENABLED=false`.
5. Event Mirror: новое сообщение в группе по-прежнему попадает в зеркало (smoke по `studio_messages` / админке).

## Текущая цель

Выкатить на VPS образы с **single-brain** + **`studio-mcp`**; в Memoh Admin подключить MCP и skill; пройти §11; зафиксировать hash в этом файле.

## Что уже работает

- **Single-brain + MCP (май 2026):** Memoh без nl-gate; Studio без NL в beat; **`studio-mcp`** + 11 tools; см. `docs/06_DECISIONS.md`, `docker-compose.prod.yml`, `skills/pb-studio-manager/SKILL.md`.
- Фазы 0–14c по Studio: см. `docs/04_PROJECT_LOG.md` и `docs/03_IMPLEMENTATION_PLAN.md`.
- **MVP стабилизация:** операторский гайд `docs/15_OPERATOR_GUIDE.md`; коммиты **`e6e4a13f`** (код+доки), **`8d2b41d3`** (ссылки на hash), **`7a4a8a10`** (Celery: `dispose_engine` после `run_control_commands_standalone`, чтобы worker не ловил *different event loop*); Memoh group final-only; beat `process_control_group_commands`; `/kb_help` без `STUDIO_KB_ENABLED`; парсер `@bot`; `/admin/control-commands` — см. `docs/04_PROJECT_LOG.md`.
- **NL слой (архив conversational):** Alembic **`017`+`018`**, пакет **`pb_studio/nl`** (legacy/debug), HTTP **`POST …/nl-gate`** при `STUDIO_NL_COMMANDS_ENABLED`; Celery **`process_nl_interactions`** — stub; Memoh **`internal/studio`** удалён. См. `docs/06_DECISIONS.md`, `docs/04_PROJECT_LOG.md`.
- **NL turn isolation / UX / anti–off-by-one:** исторические улучшения NL worker и gate; модульные тесты **`test_nl_ux_regression`** / **`test_nl_turn_isolation`** помечены **skip** после архивации NL responder. См. коммиты до **`f22fd204`**.
- **14c:** VPS **148.253.209.54**, **jar.pb-web.ru**, health/admin/smoke/backup; `.env.prod` только на сервере (не в git); см. `docs/08_RUNBOOK_PRODUCTION.md`, `docs/06_DECISIONS.md`.
- **VPS E2E smoke:** `deploy/scripts/vps-e2e-smoke.sh` — автоматизированный чеклист (compose, DB, admin, API smoke, бэкапы); **PASS** + ожидаемые **SKIP** на текущих флагах/образе; см. `docs/04_PROJECT_LOG.md`.
- **14b:** smoke + валидация `.env.prod`, restore/KB backup scripts, расширенный runbook; см. `docs/08_RUNBOOK_PRODUCTION.md`, `deploy/scripts/`, `docs/06_DECISIONS.md`.
- **14a:** prod compose + `.env.prod.example` + runbook/backup/Caddy skeleton; см. `docs/06_DECISIONS.md`.
- **13a:** каркас Studio Admin, read-only списки; см. `docs/06_DECISIONS.md`.
- **13b:** детали и HTML-формы в `/admin/*`; см. `docs/06_DECISIONS.md`.
- **13c:** фильтры, пагинация, breadcrumbs, мобильное меню, форматирование дат; см. `docs/06_DECISIONS.md`.
- **12a:** импорт экспорта Telegram Desktop JSON в Event Mirror (`/history-import/*`), jobs в БД.
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
- **Проверка 4b:** зафиксирована в журнале; Studio: `pytest studio/tests/` (в т.ч. **`test_nl_phase.py`** для legacy gate); Go NL gate тесты удалены вместе с пакетом **`internal/studio`**.

## Что ещё не готово

- LLM-сводки и прочие сценарии **6+**; расширенный Studio Admin (HTMX и т.п.) — только по отдельной постановке.

## Идентификаторы коммитов (история 4b)

- **Реализация Go-hook 4b:** `67bc573d1b5891f6cf9d3613580f59ca92200ec9`
- **Коммит записи проверки 4b в доках:** `1c8f9f6c0ef1ec71e78c3dcc92879c8c3b8c2b42`
- **Актуальный корень ветки:** `git rev-parse HEAD` на `pb-studio/main`.
- **Фаза 14c (fix Alembic `version_num` длины ревизий):** `f8dbd06e09f7b081733061ca1c6aefcf9b727afb`

**Код Event Mirror Studio (фаза 4a, якорь):** `eb0bdcd94699215118cd9aee41b5827453c21b7f`

**ADR (только текст):** `60a319773fc545be147a29625e3121613002bd7f`

## Файлы Memoh (актуально)

- **Telegram adapter / streaming:** `internal/channel/adapters/telegram/telegram.go`, `stream.go`, `stream_test.go` (upstream streaming для групп).
- **Studio → Memoh hook (4b):** `studio_event_mirror.go`, `studio_event_mirror_test.go`.

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
- **Фаза 12a:** импорт Telegram Desktop JSON в Event Mirror + jobs API; см. `docs/06_DECISIONS.md`.
- **Фаза 13a:** Studio Admin skeleton — read-only `/admin/*`; см. `docs/06_DECISIONS.md`.
- **Фаза 13b:** детали + HTML-формы в Studio Admin (те же сервисы, что REST); flash без секретов; см. `docs/06_DECISIONS.md`.
- **Фаза 13c:** фильтры, пагинация и полировка списков в Studio Admin; см. `docs/06_DECISIONS.md`.
- **Фаза 14c:** первый deploy Studio на VPS + домен; инцидент `set -x` / ротация admin token — см. `docs/06_DECISIONS.md`, `docs/08_RUNBOOK_PRODUCTION.md`.
- **MVP стабилизация:** Memoh = runtime/ассистент; Studio = mirror + slash-команды + бизнес-данные; beat для control commands; **`8af1537d`** — исправление **500** на **`GET /admin/assistant-rules`** (NameError из‑за пропущенных импортов); см. `docs/15_OPERATOR_GUIDE.md`, `docs/06_DECISIONS.md`, `docs/04_PROJECT_LOG.md`.
- **Фаза 14b:** deploy readiness — checklist, `validate_env_prod.py`, `smoke-prod.sh`, restore/backup KB; см. `docs/06_DECISIONS.md`, `docs/08_RUNBOOK_PRODUCTION.md`.
- **Фаза 14a:** prod compose + env example + runbook/backup/Caddy skeleton; см. `docs/06_DECISIONS.md`, `docs/08_RUNBOOK_PRODUCTION.md`.

## Следующая задача

- Оператор: выкат образов (**`c1afe432`** Memoh, **`f22fd204`** Studio + Alembic **`018`**) + §11 live; затем обновить «последний стабильный commit» в этом файле.

## Вопросы к GPT

- Нет.
