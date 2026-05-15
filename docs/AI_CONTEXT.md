# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**MVP-стабилизация (май 2026)** — зафиксировано разделение ролей **Memoh vs Studio** (`docs/15_OPERATOR_GUIDE.md`, `docs/06_DECISIONS.md`). Рабочий репозиторий на VPS: **`/opt/pb-studio/pb-memoh-studio`**, ветка **`origin/pb-studio/main`**.

- **Studio Admin:** **https://jar.pb-web.ru/admin/** — в т.ч. назначение active control group (**коммит `dd285584`**), обзор с подсказкой ролей, **`/admin/control-commands`** (журнал slash-команд + кнопка «Обработать pending»).
- **Memoh Web:** **https://memo.pb-web.ru** — UI Memoh; **Memoh server** на том же VPS обрабатывает входящий Telegram (long polling); в коде: **`b0e7b510`** — таймаут long poll Bot API и **redaction** полных URL с токеном в логах.
- **Группы Telegram (Memoh):** по умолчанию без потокового `editMessageText` для group/supergroup — один финальный `sendMessage` (`MEMOH_TELEGRAM_GROUP_STREAMING_ENABLED` не truthy → режим *group final only* в `internal/channel/adapters/telegram/stream.go`), чтобы убрать дубли, «……» и зависший typing.
- **Studio control commands:** парсинг `/cmd@BotName`; **`/kb_help`** и подсказка для `unknown` работают **даже при** `STUDIO_KB_ENABLED=false` (остальные `/kb_*` — только при включённом KB). **Celery beat** вызывает `pb_studio.worker.process_control_group_commands` каждые **`STUDIO_CONTROL_COMMANDS_INTERVAL_SECONDS`** (дефолт 5 с).
- **Якорь миграций (репо):** **`f8dbd06e09f7b081733061ca1c6aefcf9b727afb`** (`006`: `alembic_version.version_num` → `VARCHAR(255)`). Инцидент **`set -x`** / утечка **`STUDIO_ADMIN_TOKEN`** — токен на VPS **ротирован**; см. `docs/08_RUNBOOK_PRODUCTION.md`, `docs/06_DECISIONS.md`.
- **Security / `TELEGRAM_BOT_TOKEN`:** если токен бота когда-либо оказывался в логах (в т.ч. до правок redaction) — **ротация в BotFather и обновление в Memoh + Studio `.env.prod`** остаётся действием оператора; до подтверждения в журнале/тикете финальный статус **USER_ACTION_REQUIRED** (не считать инцидент закрытым только правкой логирования).

**VPS (2026-05-15):** на **148.253.209.54** выполнен выборочный деплой: `git reset --hard origin/pb-studio/main` → **HEAD `7a4a8a106974b4ce1a67bd3677bef280048e54d3`** (включает **`8d2b41d3`** + MVP **`e6e4a13f`** + **`fix(celery): dispose async engine after control commands standalone`**). Пересобраны **memoh-jar `server`**, **studio-api / studio-worker / studio-beat**. Health: **memo.pb-web.ru** и **jar.pb-web.ru/admin** — **200**; `getMe` → **jarvispbweb_bot** / **ИИ Purple Bear**; **webhook пустой**; **pending_update_count=0**. Active control group по API: **Управление Jarvis**, **telegram_chat_id=-1003903704506**, **studio_chat_uuid=863b1234-0ccf-45c2-a1c3-e3b0b0479863**. В БД уже есть **`kb_help` → processed** с **`response_telegram_message_id` не null** (исторические прогоны); вариант **`/kb_help@jarvispbweb_bot`** в `studio_control_commands` на момент проверки **не встречался** — нужна ручная отправка для финального PASS. Маркеры **`mvp-private-001`** / **`mvp-group-mention-001`** в `studio_messages` **не найдены** (сообщения пользователем ещё не отправлялись после деплоя). **vps-e2e-smoke.sh:** логи worker **PASS** после фикса Celery; остаются **FAIL** только **`/admin/assistant-rules` (500)** — вне MVP-чеклиста slash-команд; **SKIP**: history import, live Telegram-блок скрипта, pytest в образе.

**VPS E2E smoke** — см. абзац выше; ожидаемые **SKIP** без изменений: history import, **12_telegram** (ручной CG), **14_pytest**.

**Фаза 12a** — `POST /history-import/telegram-json`, jobs в БД. **Фаза 11b** — правила в KB RAG. Фазы **10g**–**10e** — см. журнал.

## Текущая цель

Закрыть MVP по чеклисту приёмки (личка / control group / `/kb_help` / mirror / админка / доки) **без** новых крупных фич; дальнейшие **6+**, **13+**, **10+** — отдельными задачами после стабильного MVP.

## Что уже работает

- Фазы 0–14c по Studio: см. `docs/04_PROJECT_LOG.md` и `docs/03_IMPLEMENTATION_PLAN.md`.
- **MVP стабилизация:** операторский гайд `docs/15_OPERATOR_GUIDE.md`; коммиты **`e6e4a13f`** (код+доки), **`8d2b41d3`** (ссылки на hash), **`7a4a8a10`** (Celery: `dispose_engine` после `run_control_commands_standalone`, чтобы worker не ловил *different event loop*); Memoh group final-only; beat `process_control_group_commands`; `/kb_help` без `STUDIO_KB_ENABLED`; парсер `@bot`; `/admin/control-commands` — см. `docs/04_PROJECT_LOG.md`.
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

- LLM-сводки и прочие сценарии **6+**; расширенный Studio Admin (HTMX и т.п.) — только по отдельной постановке.

## Идентификаторы коммитов (история 4b)

- **Реализация Go-hook 4b:** `67bc573d1b5891f6cf9d3613580f59ca92200ec9`
- **Коммит записи проверки 4b в доках:** `1c8f9f6c0ef1ec71e78c3dcc92879c8c3b8c2b42`
- **Актуальный корень ветки:** `git rev-parse HEAD` на `pb-studio/main`.
- **Фаза 14c (fix Alembic `version_num` длины ревизий):** `f8dbd06e09f7b081733061ca1c6aefcf9b727afb`

**Код Event Mirror Studio (фаза 4a, якорь):** `eb0bdcd94699215118cd9aee41b5827453c21b7f`

**ADR (только текст):** `60a319773fc545be147a29625e3121613002bd7f`

## Файлы Memoh (актуально)

- **Telegram adapter / streaming:** `internal/channel/adapters/telegram/telegram.go`, `stream.go`, `stream_test.go`.
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
- **MVP стабилизация:** Memoh = runtime/ассистент; Studio = mirror + slash-команды + бизнес-данные; beat для control commands; см. `docs/15_OPERATOR_GUIDE.md`, `docs/06_DECISIONS.md`, `docs/04_PROJECT_LOG.md`.
- **Фаза 14b:** deploy readiness — checklist, `validate_env_prod.py`, `smoke-prod.sh`, restore/backup KB; см. `docs/06_DECISIONS.md`, `docs/08_RUNBOOK_PRODUCTION.md`.
- **Фаза 14a:** prod compose + env example + runbook/backup/Caddy skeleton; см. `docs/06_DECISIONS.md`, `docs/08_RUNBOOK_PRODUCTION.md`.

## Следующая задача

- Подтвердить в Telegram после деплоя: **`mvp-private-001 привет`** в личку; **`@jarvispbweb_bot mvp-group-mention-001 ты тут?`** в группе; **`/kb_help`** и **`/kb_help@jarvispbweb_bot`** в control group. При необходимости — **ротация `TELEGRAM_BOT_TOKEN`** (статус **USER_ACTION_REQUIRED**, пока оператор не подтвердил). Отдельно: разобрать **HTTP 500** на **`/admin/assistant-rules`** (список), если нужен чистый smoke без FAIL.

## Вопросы к GPT

- нет
