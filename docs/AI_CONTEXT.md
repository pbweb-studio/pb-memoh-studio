# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**После 14c** — первый **staging/prod deploy** Studio на VPS **148.253.209.54**, домен **https://jar.pb-web.ru** (Caddy → `127.0.0.1:8000`). Проверены: `GET /health`, `/admin/login`, `smoke-prod.sh`, `backup-postgres.sh`. **Memoh не менялся.** Якорь миграций в репо: **`f8dbd06e09f7b081733061ca1c6aefcf9b727afb`** (`006`: расширение `alembic_version.version_num` до `VARCHAR(255)`). Инцидент с утечкой `STUDIO_ADMIN_TOKEN` в лог из‑за `set -x` — зафиксирован в `docs/08_RUNBOOK_PRODUCTION.md` и `docs/06_DECISIONS.md`; токен на VPS ротирован.

**VPS E2E smoke** — скрипт `deploy/scripts/vps-e2e-smoke.sh` / `vps-e2e-smoke.py`: compose, логи, health (`env=production`), админ (редирект без auth через `curl` без follow), alembic/таблицы, Admin UI + фильтры, API smoke (проект `smoke-*`, правило, KB, embeddings/search при включённом KB), SLA при флаге, бэкапы Postgres/KB. Итог прогона: **PASS** + **SKIP** (RAG без chat key / выключен; Telegram без токена; history import выключен; **pytest** в prod-образе не установлен — ожидаемо, полный `pytest` в CI или dev-окружении). Секреты в вывод не попадают.

**После 14b** — readiness: `docs/08_RUNBOOK_PRODUCTION.md`, `validate_env_prod.py`, `smoke-prod.sh`, restore/KB backup, `.env.prod.example`.

**После 14a** — `docker-compose.prod.yml`, `.env.prod.example`, `deploy/`, runbook.

**После 13c** — Studio Admin: **13a** + **13b** + **13c** (фильтры, пагинация, breadcrumbs, offcanvas, форматирование дат).

**Фаза 12a (Studio: Telegram Desktop JSON → Event Mirror)** — `POST /history-import/telegram-json`, `GET /history-import/jobs*`, таблица `studio_history_import_jobs`; `STUDIO_HISTORY_IMPORT_ENABLED` + `STUDIO_ADMIN_TOKEN`; запись в `studio_chats` / `studio_messages` (без Memoh/Bot API).

**Фаза 11b (Studio: assistant rules → KB RAG)** — активные правила в user-prompt `ask_knowledge_base` (global + project при `project_id` + chat при `chat_id`); `POST /knowledge/ask` — `applied_rule_ids`, опциональный `chat_id`; `/kb_ask` использует `studio_chats.id` control group для chat-rules. **Без** Memoh и без применения правил к сводкам/SLA/digest.

Фазы **10g** (Telegram → KB), **10f** (HTTP KB), **10e** — см. журнал.

## Текущая цель

Расширение Admin UI (**13+**), **6+** (LLM для сводок и пр.), **10+**, донастройка staging (**Telegram**/RAG-ключи на VPS) — по отдельной постановке.

## Что уже работает

- Фазы 0–14c по Studio: см. `docs/04_PROJECT_LOG.md` и `docs/03_IMPLEMENTATION_PLAN.md`.
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
- **Проверка 4b:** зафиксирована в журнале; актуальные тесты Studio: `pytest tests/` (число кейсов — после последнего полного прогона, см. журнал).

## Что ещё не готово

- Расширенный Studio Admin (формы, HTMX, мутации) без отдельной постановки; прочие сценарии 6+.

## Идентификаторы коммитов (история 4b)

- **Реализация Go-hook 4b:** `67bc573d1b5891f6cf9d3613580f59ca92200ec9`
- **Коммит записи проверки 4b в доках:** `1c8f9f6c0ef1ec71e78c3dcc92879c8c3b8c2b42`
- **Актуальный корень ветки:** `git rev-parse HEAD` на `pb-studio/main`.
- **Фаза 14c (fix Alembic `version_num` длины ревизий):** `f8dbd06e09f7b081733061ca1c6aefcf9b727afb`

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
- **Фаза 12a:** импорт Telegram Desktop JSON в Event Mirror + jobs API; см. `docs/06_DECISIONS.md`.
- **Фаза 13a:** Studio Admin skeleton — read-only `/admin/*`; см. `docs/06_DECISIONS.md`.
- **Фаза 13b:** детали + HTML-формы в Studio Admin (те же сервисы, что REST); flash без секретов; см. `docs/06_DECISIONS.md`.
- **Фаза 13c:** фильтры, пагинация и полировка списков в Studio Admin; см. `docs/06_DECISIONS.md`.
- **Фаза 14c:** первый deploy Studio на VPS + домен; инцидент `set -x` / ротация admin token — см. `docs/06_DECISIONS.md`, `docs/08_RUNBOOK_PRODUCTION.md`.
- **Фаза 14b:** deploy readiness — checklist, `validate_env_prod.py`, `smoke-prod.sh`, restore/backup KB; см. `docs/06_DECISIONS.md`, `docs/08_RUNBOOK_PRODUCTION.md`.
- **Фаза 14a:** prod compose + env example + runbook/backup/Caddy skeleton; см. `docs/06_DECISIONS.md`, `docs/08_RUNBOOK_PRODUCTION.md`.

## Следующая задача

- По постановке: **13+**, **6+**, расширение **10+**, донастройка **jar.pb-web.ru** (секреты Telegram/RAG на VPS) — по постановке.

## Вопросы к GPT

- нет
