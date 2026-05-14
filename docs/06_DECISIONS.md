# Решения и зафиксированные варианты

## Git / репозитории

- **`upstream`**: https://github.com/memohai/Memoh.git — эталон Memoh.
- **`origin`**: https://github.com/pbweb-studio/pb-memoh-studio.git — рабочий репозиторий студии (создан вручную).
- Рабочая ветка: **`pb-studio/main`**.
- Тег **`stable-upstream-memoh`**: аннотированный снимок upstream до студийных коммитов.

## Продукт / платформа

- Один Telegram-бот; второй бот не вводим.
- Системные уведомления в Telegram — **только** в настроенную управляющую группу; если группа не задана — только запись в Studio DB (`studio_system_notifications`, статус `logged_only`). **Фаза 5a:** контракт и политика без исходящего API. **Фаза 5b:** исходящая доставка только в control group через Bot API `sendMessage` (см. раздел «Фаза 5b»); без нового ADR не добавляем Memoh hook для send.
- Бизнес-данные в **Studio Layer** (Postgres), не в memory Memoh как в БД.
- SLA — отдельный монитор (Celery/Beat), **не** через heartbeat Memoh.
- Event Mirror обязателен; Response Queue обязателен; интеграция Memoh ↔ Studio через **MCP/API**.
- Документы и регламенты — через **RAG**, не хардкод в system prompt.
- Самообучение = **assistant_rules** (+ аудит), не самопереписывание кода.

## Docker (Фаза 0)

- В корне уже есть **`docker-compose.yml`** Memoh (postgres 18 для Memoh, server, web и т.д.). Его **не меняем** в Фазе 0.
- Для Studio Layer используется **отдельный** файл **`docker-compose.local.yml`**: Postgres **16** с расширением **pgvector** и **Redis** для будущих сервисов `studio-api` / worker (подключение сервисов — в Фазе 3+).
- Так локально можно поднять инфраструктуру студии одной командой, не ломая штатный compose Memoh. Вопрос `extends`/объединения с Memoh — вернёмся при интеграции (Фаза 3+).
- **`docker-compose.prod.yml`** на Фазе 0 — только скелет (Caddy + заглушки); реальный прод — Фаза 14. Добавлен минимальный [`deploy/Caddyfile`](deploy/Caddyfile) чтобы compose не ссылался на пустой путь.

## Фаза 4a — Event Mirror ingest (только Studio)

- Реализация: `POST /events/telegram`, таблицы `studio_*` (см. `studio/pb_studio/event_mirror/`, Alembic `002_event_mirror`).
- **Без** правок Memoh и **без** исходящих вызовов Telegram API; управляющая группа / сводки / RAG / SLA — вне scope 4a.
- Опциональный enqueue в Response Queue: только при `STUDIO_MIRROR_ENQUEUE_USER_MESSAGES=true` и только для пользовательских text/caption в private/group/supergroup; по умолчанию выключено (см. `docs/03_IMPLEMENTATION_PLAN.md`).
- Поставка событий из реального Telegram/Memoh в этот endpoint — отдельная подфаза (4b+), после выбора A/B/C для точки интеграции.

## Фаза 5a — управляющая группа (Studio)

- Реализация: `studio/pb_studio/control_group/`, расширение `studio_chats.chat_role`, таблицы `studio_control_groups`, `studio_chat_roles`, `studio_system_notifications`, Alembic `003_control_group`.
- **Без** Memoh-изменений; **без** исходящего Telegram API в 5a; второй бот и смена polling/webhook **не** используются.
- Системные уведомления по `my_chat_member` после Event Mirror: запись в БД; при активной управляющей группе статус `pending_for_control_group_delivery`, иначе `logged_only`; доставка **не** планируется в исходный чат события (`payload.delivery_policy = control_group_only`).
- Админ-API: `GET /control-group`, `POST /control-group/set`, `GET /chats`, `GET /chats/unassigned`, `POST /chats/{studio_chat_uuid}/role`; при `STUDIO_ADMIN_TOKEN` — Bearer обязателен.
- Сводки (6+), SLA (8), RAG, Studio Admin — вне scope 5a/5b.

## Фаза 5b — outbound: system notifications → Telegram control group (Studio)

- **Транспорт:** Telegram Bot API **только** `sendMessage` (HTTP, например `httpx`); **без** `getUpdates`, **без** webhook из Studio; **без** второго бота — тот же `TELEGRAM_BOT_TOKEN`, что и у остального контура (Memoh остаётся владельцем входящего потока).
- **Куда:** исключительно `chat_id` **активной** записи `studio_control_groups` → связанный `studio_chats` с `chat_role = control_group`. Не в исходный чат события; не в `client_chat` / `project_chat` / `internal_chat` / `service_chat` (роль destination проверяется перед отправкой).
- **Флаги:** `STUDIO_SYSTEM_NOTIFICATIONS_ENABLED` (по умолчанию `false`); без включения и без токена — доставка не выполняется, строки в БД не теряются.
- **Надёжность:** при ошибках API — статусы `failed_retryable` / `failed_permanent`, `retry_count`, `last_error`; идемпотентный батч; повторный запуск не дублирует уже `delivered_to_control_group`.
- **Аудит:** попытки доставки фиксируются в `studio_audit_log` (`control_group.system_notification_delivered`, `control_group.system_notification_delivery_failed`, `control_group.system_notification_delivery_blocked`, `control_group.system_notification_delivery_refused` и т.д.); в payload логов **не** попадает сырой токен (редакция).
- **Операции:** Celery-задача `deliver_pending_system_notifications`; опционально `GET /notifications/system`, `POST /notifications/system/deliver-pending` под `STUDIO_ADMIN_TOKEN`.

## Фаза 6a — сводки: инфраструктура без LLM (Studio)

- Таблица `studio_chat_summaries`: задания `pending` / `generated` / `failed` по чату и периоду; снимок `chat_role` на момент планирования; `source_event_count` считается **только** по строкам Event Mirror (`studio_messages`, `studio_chat_lifecycle_events`) в полуинтервале периода.
- **Без** вызовов Memoh, **без** LLM, **без** генерации текста сводки в 6a, **без** `sendMessage` сводок в Telegram; второй бот и polling/webhook **не** добавляются.
- Идемпотентность: уникальность `(chat_id, summary_type, period_start, period_end)`.
- API под `STUDIO_ADMIN_TOKEN`: `GET /summaries`, `POST /summaries/plan`, `GET /summaries/{id}`; Celery `plan_daily_chat_summaries` — только создание pending daily jobs за «вчера» (UTC).

## Фаза 6b — сводки: шаблонная генерация summary_text (Studio)

- **Источник данных:** только Event Mirror в Postgres (`studio_messages`, `studio_chat_lifecycle_events`); **без** RAG, **без** вызовов Memoh, **без** внешних LLM API (`httpx` к OpenAI и т.п. не используется).
- **Результат:** для `pending` заполняется детерминированный `summary_text`, `status=generated`, `generated_at`, пересчёт `source_event_count`; пустой период — текст «За период новых событий нет.»; при ошибке строки — `failed` + `last_error`, батч продолжается.
- **Флаги:** `STUDIO_SUMMARY_GENERATION_ENABLED` (по умолчанию `false`); лимиты `STUDIO_SUMMARY_MAX_SOURCE_MESSAGES`, `STUDIO_SUMMARY_MAX_BULLETS`.
- **Операции:** Celery `generate_pending_chat_summaries`; `POST /summaries/generate-pending`, `POST /summaries/{id}/generate` под `STUDIO_ADMIN_TOKEN`.
- **Не делается:** отправка сводок в Telegram (`sendMessage` для сводок), второй бот, polling/webhook.

## Фаза 6c — сводки: продуктовый HTTP API по чату (Studio)

- **Назначение:** удобные вызовы «сегодня / вчера / произвольный период / последняя generated» по `studio_chats.id` (UUID в пути), поверх уже существующих `plan_summary_job` + шаблонного `apply_generation_to_row` (6b).
- **Авторизация:** те же админ-зависимости, что и остальные защищённые роуты — при заданном `STUDIO_ADMIN_TOKEN` обязателен `Authorization: Bearer …`.
- **Семантика:** если за период уже есть строка `generated` — возврат без дубликата; если `pending` — генерация и возврат; если строки нет — `plan` + генерация; периоды today/yesterday считаются в **UTC**; для `failed` за тот же период — HTTP **409** (ручное вмешательство в БД).
- **Не делается:** Memoh, внешние LLM HTTP, `sendMessage` для сводок, RAG, SLA, проекты, Studio Admin UI, изменения polling/webhook, второй бот.

## Фаза 6d — сводки: доставка в Telegram control group (Studio)

- **Транспорт:** только Bot API `sendMessage` через существующий `telegram_send_message` (httpx к `api.telegram.org`); тот же `TELEGRAM_BOT_TOKEN`, что и у 5b; **без** второго бота, **без** polling/webhook из Studio.
- **Куда:** только `chat_id` активной записи `studio_control_groups` → `studio_chats` с ролью `control_group`. Не в исходный чат сводки (`row.chat_id`), не в `client_chat` / `project_chat` / `internal_chat` / `service_chat` как destination; если роль destination не `control_group` — блокировка и `failed_permanent` по доставке; если исходный `telegram_chat_id` совпадает с destination — отказ (`refused`).
- **Состояния доставки:** `not_requested`, `pending_control_group_delivery`, `delivered_to_control_group`, `failed_retryable`, `failed_permanent`; при отсутствии control group строка сводки **не** теряется — остаётся `pending` с `delivery_last_error`.
- **Флаги:** `STUDIO_SUMMARY_DELIVERY_ENABLED` (по умолчанию `false`); `STUDIO_SUMMARY_DELIVERY_MAX_RETRIES`; токен и таймаут — как у 5b (`TELEGRAM_BOT_TOKEN`, `STUDIO_TELEGRAM_SEND_TIMEOUT_MS`).
- **Аудит:** `summaries.delivery_*`; в `delivery_last_error` и payload **не** попадает сырой токен (редукция через `redact_secrets`).
- **Не делается:** Memoh, LLM, RAG, SLA, проекты, Studio Admin.

## Фаза 7a — команды сводок из control group (Studio, Event Mirror как вход)

- **Вход:** только строки `studio_messages` чата активной `studio_control_groups` (роль `control_group`); сообщения в `client_chat` / `project_chat` / `internal_chat` / `service_chat` **не** сканируются как источник команд (у них другой `chat_id`).
- **Команды:** `/summary_today|yesterday|period|latest|help` + текстовые ошибки в control group; парсер отбрасывает не-команды и сообщения от `is_bot`; ответы только через `sendMessage` в control group (инъектируемый `send_message` в тестах).
- **Обработка:** `summaries/product.py` (`ensure_chat_summary_for_period`, `get_latest_generated_for_chat`); при `STUDIO_SUMMARY_DELIVERY_ENABLED` — доставка 6d, иначе текстовый ответ со сводкой; идемпотентность по `source_message_id` / `source_update_id` в `studio_control_commands`; `SQLAlchemy.begin_nested` при гонке вставок.
- **Флаги:** `STUDIO_CONTROL_COMMANDS_ENABLED` (по умолчанию `false`), `STUDIO_CONTROL_COMMANDS_MAX_BATCH` (по умолчанию `50`); Celery `process_control_group_summary_commands`; админ `GET /control-commands`, `POST /control-commands/process-pending` при заданном `STUDIO_ADMIN_TOKEN`.
- **Не делается:** Memoh, второй бот, polling/webhook Studio, LLM/RAG/SLA/проекты/Studio Admin UI, проектные сводки.

## Фаза 7b — UX команд сводок и ACL в control group (Studio)

- **Команды:** `/summary_chats` (список `studio_chats` без активной control group, обрезка по числу строк и по лимиту Telegram); `/summary_all_today` и `/summary_all_yesterday` — один агрегированный ответ в control group по всем чатам кроме control group, через `ensure_chat_summary_for_period` без дублирования jobs (идемпотентность product); обновлён `/summary_help`.
- **ACL:** `STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS` — CSV/пробелы/точка с запятой; пусто = все участники; иначе только `message.from.id` из зеркала; отказ — `sendMessage` с коротким текстом, статус команды `failed_access_denied`, аудит `control_commands.access_denied` (payload без токена); `last_error` при прочих сбоях через `redact_secrets`.
- **API:** `GET /control-commands` — опциональные query `status`, `command_name`; `POST /control-commands/process-pending` без изменения контракта (в счётчиках process может быть `access_denied`).
- **Не делается:** Memoh, второй бот, polling/webhook Studio, LLM/RAG/SLA/проекты/Studio Admin UI, проектные команды.

## Фаза 8a — SLA-инфраструктура по чатам (Studio, Event Mirror, без LLM)

- **Источник:** только `studio_messages` и роли чатов в Studio DB; учитываются **только** `client_chat` и `project_chat`.
- **Логика:** последнее пользовательское входящее (`from.is_bot` false) без последующего сообщения от бота в том же чате; просрочка `first_response_minutes` (активная `studio_sla_policies` по `chat_role` или `STUDIO_SLA_DEFAULT_FIRST_RESPONSE_MINUTES`) → инцидент `open`, `severity` breached; partial unique на `(chat_id, trigger_message_id)` при `status=open`; ответ бота после триггера → `resolved`; смена «хвоста» без ответа → superseded / `resolved`.
- **Уведомления:** только активная control group (`sendMessage`); без CG — только БД; лимит `STUDIO_SLA_MAX_NOTIFICATIONS_PER_INCIDENT`, опционально `followup_minutes` в policy; ошибки Telegram не прерывают детектор; `last_error` через `redact_secrets`.
- **Флаги / API:** `STUDIO_SLA_ENABLED`, `STUDIO_SLA_DEFAULT_FIRST_RESPONSE_MINUTES`, `STUDIO_SLA_MAX_NOTIFICATIONS_PER_INCIDENT`; Celery `detect_sla_incidents`; админ `GET /sla/incidents`, `POST /sla/detect`, ack/resolve, `GET/POST /sla/policies` при `STUDIO_ADMIN_TOKEN`.
- **Не делается:** Memoh, второй бот, polling/webhook Studio, LLM/RAG, проектная привязка, Studio Admin UI, отправка уведомлений в client/project/internal/service чаты.

## Фаза 8b — рабочие часы и mute для SLA (Studio DB, без LLM)

- **Календарь:** колонка `timezone` (IANA) на policy; `working_days_json` (ISO 1–7, по умолчанию пн–пт), `working_hours_start` / `working_hours_end` (`HH:MM`), `holidays_json` (`YYYY-MM-DD` и/или `MM-DD`); глобальный флаг `STUDIO_SLA_WORKING_HOURS_ENABLED` — при `false` дедлайн как в 8a; при `true` — `calculate_due_at` считает только рабочие минуты, старт SLA с ближайшего рабочего окна вне графика; `STUDIO_SLA_DEFAULT_TIMEZONE` при отсутствии policy или для дефолтного TZ.
- **Mute:** `is_muted` или `muted_until` в будущем блокирует **только создание** новых инцидентов; открытые инциденты и уведомления по ним не ломаются; `POST /sla/policies/{id}/mute|unmute`, `PATCH /sla/policies/{id}`.
- **Не делается:** Memoh, LLM/RAG, проекты, Studio Admin UI.

## Фаза 8c — антиспам SLA-уведомлений в control group (Studio DB, без LLM)

- **Аудит:** `studio_sla_notification_events` (status sent/suppressed/failed); на инциденте — `next_notification_at`, счётчик подавлений, `last_notification_reason`.
- **Поведение:** первое уведомление сразу; повтор только при `now >= next_notification_at`, интервал `max(STUDIO_SLA_NOTIFICATION_COOLDOWN_MINUTES, followup_minutes)` если followup задан; при достижении лимита `STUDIO_SLA_MAX_NOTIFICATIONS_PER_INCIDENT` — suppress без `sendMessage`; за один прогон детектора несколько инцидентов → один digest (до `STUDIO_SLA_NOTIFICATION_DIGEST_MAX_ITEMS` + «и ещё N»), обрезка по `STUDIO_SLA_NOTIFICATION_TEXT_MAX_LEN`; ошибки Telegram → `failed` в событиях, детектор продолжает.
- **API:** `GET /sla/notification-events`, `POST /sla/incidents/{id}/notify` (ручной notify, обход cooldown, не лимита); фильтры на списке инцидентов.
- **Не делается:** Memoh, второй бот, polling/webhook Studio, LLM/RAG, проекты, Studio Admin UI, отправка в client/project/internal/service чаты.

## ADR — Telegram / Memoh → Studio Event Mirror (`POST /events/telegram`) перед фазой 4b

**Статус ADR-документа:** зафиксировано в документации (таблица A/B/C); см. отдельный SHA в `docs/AI_CONTEXT.md` (**ADR commit**).

**Статус транспорта 4b:** **вариант C утверждён и реализован** — минимальный hook в [`internal/channel/adapters/telegram/studio_event_mirror.go`](internal/channel/adapters/telegram/studio_event_mirror.go) + одна вставка в [`internal/channel/adapters/telegram/telegram.go`](internal/channel/adapters/telegram/telegram.go) после дедупа `update_id`. Второй бот, внешний gateway и смена владельца getUpdates/webhook **не** используются; при недоступности Studio Memoh только логирует и продолжает работу.

Инжест Studio уже есть (**фаза 4a**): `POST /events/telegram`, идемпотентность по `update_id`, нормализация в Postgres. Ниже — как **сырой** Telegram `Update` может попадать в этот endpoint и как Memoh остаётся в контуре.

### Сводная таблица (A / B / C)

| Критерий | **A — внешний gateway / proxy** | **B — patch в Memoh (adapter / inbound)** | **C — минимальный hook / API + Studio** |
|----------|----------------------------------|---------------------------------------------|------------------------------------------|
| **Какие файлы меняются** | В основном **Studio** и инфра: reverse-proxy / edge (Caddy, Nginx), `studio-api` или отдельный webhook-сервис, `docker-compose*`, секреты, DNS/BotFather webhook URL. Memoh — **только конфиг/деплой** (отключить второй получатель Telegram для того же бота), **без** правок Go **если** Memoh больше не должен получать webhook. | **Memoh:** `internal/channel/adapters/telegram/telegram.go`, при необходимости `internal/channel/inbound.go`, `internal/channel/inbound/channel.go`, тесты рядом. **Studio:** клиент к Memoh (вызов после зеркала). | **Memoh:** один **узкий** слой (новый internal HTTP handler, gRPC, или 5–20 строк в месте после десериализации update) — согласовать с мейнтейнерами. **Studio:** HTTP-клиент / очередь, без дублирования бизнес-логики Memoh. |
| **Как update попадает в `POST /events/telegram`** | Telegram шлёт webhook (или long poll) **только** на Studio; Studio сохраняет JSON и **отдельно** решает, как передать «сообщение для агента» в Memoh (HTTP/MCP/ещё один внутренний контракт). Memoh **не** видит сырой `Update`, если не продублировать поток. | В `telegram.go` после получения `Update` (или в `dispatchInbound`): **HTTP POST** (или очередь) в Studio с тем же JSON; далее существующий путь Memoh **как сейчас** обрабатывает inbound (или сначала Studio, потом Memoh — порядок нужно зафиксировать). | После валидации update в Memoh вызывается **согласованный** вызов Studio (fire-and-forget или sync): тот же JSON в `POST /events/telegram`; Memoh продолжает свой `HandleInbound` по текущему продукту. |
| **Риск потерять update** | **Средний:** при падении Studio до ack Telegram может ретраить webhook; при ошибке между «записали в Studio» и «доложили в Memoh» нужна **явная** семантика (outbox, retry, DLQ). Два независимых потребителя одного бота без координации — дубли или пропуски. | **Низкий–средний:** если зеркалирование в Studio **асинхронно** и падает, Memoh уже мог принять update — Studio отстанет; нужен retry/outbox из Memoh в Studio. | **Низкий:** update уже внутри процесса Memoh; сбой вызова Studio должен логироваться и **ретраиться** (иначе зеркало отстаёт, но Memoh не теряет). |
| **Риск сломать Memoh** | **Низкий** по коду Memoh; **высокий** по продукту, если Memoh всё ещё подписан на тот же webhook / polling — два клиента на одном токене. Нужна чёткая схема «один получатель raw». | **Высокий:** гонки и порядок уже сейчас чувствительны (`go handler()` per update, inbound pool); любой patch — риск регрессий и расхождения с `upstream`. | **Средний:** точечное изменение; но любой новый API — контракт, версии, авторизация. |
| **Один Telegram-бот** | **Да**, если webhook URL **один** и Memoh не получает параллельно тот же поток. Токен хранится в Studio (или в vault) для edge; Memoh получает только «синтетический» inbound по отдельному каналу. | **Да**, один бот; дублирование трафика на Studio — осознанное решение (двойная обработка нужно избегать). | **Да**; Memoh остаётся «владельцем» сессии агента, Studio — зеркало и очередь. |
| **Сложность отката** | **Средняя:** переключить webhook обратно на Memoh; очистить/игнорировать зеркало в Studio. Зависит от DNS и BotFather. | **Высокая:** откат PR/форка; возможны миграции данных очереди. | **Средняя:** feature-flag вокруг hook; отключить вызов Studio. |
| **Как тестировать** | Контрактные тесты Studio ingest (уже есть) + e2e: фейковый Telegram webhook → Studio → (заглушка) Memoh; нагрузочный тест на дубли `update_id`. | Интеграционные тесты Memoh + поднятый `studio-api`; проверка, что при недоступности Studio Memoh не падает (политика ошибки). | Unit + e2e: один update проходит Memoh и появляется в `studio_telegram_raw_updates`; сравнение `update_id` end-to-end. |

### Рекомендация (один вариант)

**Основной выбор: вариант C** — очередь и Event Mirror остаются **источником истины** в Studio (как в текущей архитектуре 2a–4a); Memoh получает **минимальный**, явно описанный контракт «один turn / одно сообщение» после debounce, без переноса всей телеграм-логики в Studio. Тонкий hook (или согласованный internal endpoint) ограничивает поверхность изменений Memoh и сохраняет один бот в привычном процессе.

**Запасной пилот без правок Go в Memoh:** вариант **A** (Studio как единственная точка входа raw webhook) — если команда **запрещает** любые изменения в Memoh на первом этапе; тогда критично спроектировать **надёжный** мост Studio→Memoh (outbox, retry) и **отключить** параллельный приём того же бота в Memoh.

**Вариант B** оставить **крайним** средством (нужен низкий end-to-end latency внутри одного процесса и принятие форка/сопровождения отличий от upstream).

### Связь с разделом «Фаза 1 — варианты A/B/C» ниже

Блок «Фаза 1 — Response Queue / интеграция» сохраняет исторические формулировки A/B/C по очереди и Memoh. Раздел **ADR выше** уточняет их применительно к **доставке raw Update в Studio** перед 4b; при противоречии приоритет у **ADR** для решения «что кодировать дальше».

## Фаза 1 — Response Queue / интеграция (зафиксированные варианты)

Разведка: см. [`docs/03_IMPLEMENTATION_PLAN.md`](docs/03_IMPLEMENTATION_PLAN.md). Код Memoh **не менялся**.

### Вариант A — Внешний gateway (Studio держит Telegram token)

- Studio принимает **единственный** webhook/long poll от Telegram (единая точка для `getUpdates`/webhook).
- Memoh **не** получает сырые Telegram updates напрямую; Studio зеркалирует в БД и **подаёт** пользовательский текст в Memoh через внутренний контракт.
- **Плюсы:** полный контроль debounce, per-chat FIFO, статусы в Studio без гонок в `TelegramAdapter.dispatchInbound`.
- **Минусы:** нужен **стабильный способ** «вколоть» сообщение в Memoh как inbound Telegram-эквивалент (сейчас публичный путь — адаптер + `Manager.HandleInbound`; отдельного простого «simulate telegram message» API в разведке не найдено). Риск рассинхрона маршрутов/токенов.

### Вариант B — Точечный patch в Memoh (`internal/channel`)

- **B1:** В [`internal/channel/inbound.go`](internal/channel/inbound.go) — сериализация задач **по ключу** `route_id` или `bot_id+reply_target` (отдельные очереди или mutex), чтобы два быстрых сообщения одного чата не обрабатывались двумя воркерами пула параллельно.
- **B2:** В [`internal/channel/adapters/telegram/telegram.go`](internal/channel/adapters/telegram/telegram.go) — убрать/ограничить `go handler()` per update (очередь на chat_id в адаптере).
- **Плюсы:** минимальные задержки, один процесс Memoh.
- **Минусы:** форк/поддержка отличий от `upstream`; нарушает правило «не трогать ядро» без явного ADR.

### Вариант C — Очередь только в Studio + тонкий хук Memoh

- Event Mirror + Celery (Фазы 3–4) накапливают turn; **один** исходящий запрос в Memoh на turn (после согласования контракта: либо новый минимальный internal endpoint в Memoh, либо согласованный с мейнтейнерами PR).
- **Плюсы:** бизнес-очередь и статусы полностью в Studio; Memoh остаётся «один ответ за turn».
- **Минусы:** всё равно может понадобиться **небольшой** patch Memoh для безопасного inject (или договорённость о API).

### Рекомендация для Фазы 2 (черновик)

1. Параллельно поднять **Event Mirror** (Фаза 4) — не блокируется от очереди.
2. Очередь **2a** уже в коде Studio (`QueueService`); следующий шаг — **Celery/HTTP** (Фаза 3) и контракт `TurnProcessor` → Memoh.
3. Перед первым PR в Memoh — выбрать **B** vs **C** vs **A** по трудозатратам и допустимости форка; зафиксировать в новой записи в этом файле.

### Про «глазик» 👀

Не баг Telegram-адаптера как такового: подтверждение **inject** в [`internal/channel/inbound/channel.go`](internal/channel/inbound/channel.go) (`sendModeConfirmation`). Поведение продукта студии (отдельные статусы turn, без путаницы с финальным ответом) реализуется в **Studio Response Queue** и UX управляющей группы, а не заменой этого механизма без решения.

## Фаза 2a — Response Queue в Studio (безопасная часть, выполнено)

- Реализация: [`studio/pb_studio/response_queue/`](studio/pb_studio/response_queue/), DDL-скелет [`studio/migrations/001_response_queue.sql`](studio/migrations/001_response_queue.sql), тесты [`studio/tests/test_response_queue.py`](studio/tests/test_response_queue.py).
- **Не делалось намеренно:** правки Memoh, Telegram adapter, реальный Telegram runtime, Celery wiring, FastAPI-роуты продукта (часть Фазы 3).
- **Рекомендация по интеграции (без изменения текста вариантов A/B/C):** по-прежнему склоняемся к **варианту C** (очередь и статусы в Studio + минимальный контракт в Memoh), пока не доказано, что gateway (A) дешевле по сопровождению. Окончательный выбор — после прототипа Event Mirror + одного E2E без продакшена. **Согласовано с ADR перед 4b:** для доставки raw `Update` в Studio — тот же приоритет **C** (тонкий hook); **A** как запасной пилот при запрете любых патчей Memoh.

## Фаза 9a — проекты в Studio (выполнено)

- Проекты и связи чат↔проект живут только в **Studio DB** (`studio_projects`, `studio_project_chats`); источник команд — **Event Mirror** (`studio_messages` в active control group), без polling/webhook из Studio.
- Один бот; команды `/project_*` обрабатываются тем же циклом, что `/summary_*`; ответы — **только** `sendMessage` в активную control group; ACL — `STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS` (как в 7b).
- `project_bind` может выставить `chat_role=project_chat` только для `unknown` / `client_chat`; **нельзя** менять роль active control group и нельзя привязать чат с ролью `control_group`; internal/service — запрещены к bind.
- Админ-HTTP: `/projects` под тем же **`STUDIO_ADMIN_TOKEN`**, что и `/control-group`, `/summaries`, `/sla`, `/knowledge` (если токен задан — Bearer обязателен).

## Фаза 9b — project digest (выполнено)

- Дайджест проекта строится только из **Studio DB**: активные `studio_project_chats` + строки `studio_chat_summaries` через существующий **product**-пайплайн сводок; без вызова Memoh, без LLM/RAG для текста дайджеста (шаблон).
- Один бот; команды `/project_digest_*` и доставка готового дайджеста — **только** active control group (`sendMessage`); ACL — `STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS`; классификация ошибок Telegram и redact токена — как в **6d**.
- Админ-HTTP: `GET /projects/{id}/digests`, `POST .../digests/today|yesterday|period`, `GET /project-digests/{id}`, `POST .../deliver-control-group`, `POST /project-digests/deliver-pending` под **`STUDIO_ADMIN_TOKEN`**.
- Повтор за тот же период не создаёт дубликат строки digest (unique по проекту, типу и границам периода).

## Фаза 10a — knowledge base в Studio (выполнено)

- Документы, версии и чанки живут только в **Studio DB**; разбиение текста — детерминированный splitter по `STUDIO_KB_CHUNK_*`, без embeddings и без внешних LLM.
- API `/knowledge/*` включён только при **`STUDIO_KB_ENABLED=true`** и (если задан) **`STUDIO_ADMIN_TOKEN`**; команды `/kb_*` — тот же Event Mirror + ACL, ответы только в active control group.
- Повтор `POST .../versions/text` с тем же содержимым не создаёт вторую версию (unique `document_id` + `content_hash`).

## Фаза 10b — KB parse pipeline (выполнено)

- Pending-версии (`status=pending`) обрабатываются детерминированным парсером в Studio: `text/plain`, `text/markdown` → чанки; PDF/DOCX в БД **без** загруженного файла на диск (legacy defer) → `failed_unsupported` без падения батча. **Фаза 10f:** HTTP-upload с `kb_storage_relpath` + опциональный Docling. **Фаза 10g:** импорт из Telegram document в control group → тот же ingest pipeline.
- Повторный `parse` для версии в `parsed` идемпотентен (чанки не дублируются).
- Celery `parse_pending_knowledge_documents` и админ-`POST /knowledge/parse-pending` не расширяют SLA и не трогают Memoh.

## Фаза 10c — KB embeddings + vector search (выполнено)

- Эмбеддинги чанков и поиск по вектору: см. **10d** для внешнего провайдера; базово поддержан **deterministic** и pgvector/SQLite fallback.
- Включение: **`STUDIO_KB_EMBEDDINGS_ENABLED=true`** (и **`STUDIO_KB_ENABLED=true`**); размерность колонки фиксирована миграцией (**384**); env `STUDIO_KB_EMBEDDING_MODEL`, `STUDIO_KB_EMBEDDING_DIM` (должна совпадать с миграцией), `STUDIO_KB_SEARCH_TOP_K`.
- API embed/search и `/kb_search` не вызывают LLM и не генерируют «ответы RAG»; команды — только control group + ACL.

## Фаза 10d — KB внешний embedding provider (выполнено)

- **`STUDIO_KB_EMBEDDING_PROVIDER`:** `deterministic` (локально/тесты) или **`openai_compatible`** (`POST {base}/embeddings`, Bearer `STUDIO_KB_EMBEDDING_API_KEY`); батчи по `STUDIO_KB_EMBEDDING_BATCH_SIZE`, timeout `STUDIO_KB_EMBEDDING_TIMEOUT_MS`.
- Ошибки HTTP/сети и исключения пишутся в `embedding_last_error` после **redaction** ключа (`redact_secrets`); ключ не логируется из кода провайдера.
- OpenAI-батч **атомарный** (один HTTP на батч): сбой батча помечает все чанки батча `failed`, следующие батчи продолжаются; deterministic остаётся **почанковым** (`batch_atomic=false`).
- **Без** LLM chat/completion и без генерации RAG-ответов; Memoh не затрагивается.

## Фаза 10e — KB RAG question answering MVP (выполнено)

- Включение: **`STUDIO_KB_RAG_ENABLED=true`** при уже включённых **`STUDIO_KB_ENABLED`** и **`STUDIO_KB_EMBEDDINGS_ENABLED`**; chat: **`STUDIO_KB_CHAT_PROVIDER=openai_compatible`**, `STUDIO_KB_CHAT_API_BASE_URL`, `STUDIO_KB_CHAT_API_KEY`, `STUDIO_KB_CHAT_MODEL`, лимиты `STUDIO_KB_CHAT_TIMEOUT_MS`, `STUDIO_KB_RAG_TOP_K`, `STUDIO_KB_RAG_MAX_CONTEXT_CHARS`.
- Retrieval только по чанкам KB (`search_knowledge_chunks`); при пустом результате — фиксированная фраза «не найдено в базе знаний» **без** вызова LLM.
- Админ **`POST /knowledge/ask`** под `STUDIO_ADMIN_TOKEN`; **`/kb_ask`** — тот же Event Mirror + ACL, ответы только в active control group (не в client/project/internal/service чаты).
- Ошибки и ответы пользователю проходят redaction chat API key (аналогично embeddings).
- **Без** изменений Memoh, второго бота, polling/webhook Studio, Studio Admin UI.

## Фаза 10f — KB HTTP upload + Docling (выполнено)

- **`POST /knowledge/documents/upload`** и **`POST /knowledge/documents/{id}/versions/upload`** под `STUDIO_ADMIN_TOKEN` + `STUDIO_KB_ENABLED`; лимиты `STUDIO_KB_UPLOAD_MAX_BYTES`, whitelist `STUDIO_KB_ALLOWED_EXTENSIONS`; бинарники в `STUDIO_KB_STORAGE_DIR` (по умолчанию `storage/kb` или `/app/storage/kb` в compose с volume).
- **Docling:** при `STUDIO_KB_DOCLING_ENABLED=true` и установленном пакете `docling` (extras `[docling]`) — конвертация PDF/DOCX в markdown; при выключенном флаге или отсутствии пакета — `failed_unsupported`; ошибки конвертации — `failed` с redacted `last_error` (`redact_kb_import_error`).
- **Control group:** `/kb_import_help` (описание HTTP + Telegram); **фаза 10g:** `/kb_import_last`, `/kb_import_file` при `STUDIO_KB_TELEGRAM_IMPORT_ENABLED` (без polling Studio).
- **`python-multipart`** в основных зависимостях пакета для multipart API.

## Фаза 10g — KB импорт из Telegram document (выполнено)

- Включение: **`STUDIO_KB_TELEGRAM_IMPORT_ENABLED=true`** при **`STUDIO_KB_ENABLED`**, **`TELEGRAM_BOT_TOKEN`**, **`STUDIO_CONTROL_COMMANDS_ENABLED`**; источник файла — только зеркало `studio_messages` **активной** control group (`document` + `from.id`); скачивание через Bot API `getFile` + `file/bot<token>/…` с лимитом байт (`STUDIO_KB_TELEGRAM_MAX_FILE_BYTES` или `STUDIO_KB_UPLOAD_MAX_BYTES`) и timeout `STUDIO_KB_TELEGRAM_DOWNLOAD_TIMEOUT_MS`.
- Команды: **`/kb_import_last <title>`**, **`/kb_import_last --project <slug> <title>`** (последний document от отправителя **перед** message_id команды), **`/kb_import_file <telegram_file_id> <title>`**; ACL — **`STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS`**; ответы только `sendMessage` в control group; ошибки сети/API не валят батч обработки команд (`process_pending` изолирует сбои).
- Импорт в KB — тот же **`ingest_new_document_from_upload`** что HTTP **10f** (расширения `STUDIO_KB_ALLOWED_EXTENSIONS`, Docling как в 10f); токен бота и API-ключи не попадают в `last_error` пользовательских команд (redaction).

## Фаза 11b — Assistant rules в KB RAG (выполнено)

- Выборка: **`list_active_rules_for_kb_rag`** — статус **`active`**, объединение **global** + **project** (если в ask передан `project_id`) + **chat** (если передан `chat_id` в API или для `/kb_ask` — `control_group_chat_id` строки `studio_chats` активной control group).
- Промпт: блок бизнес-инструкций Studio в **user** message **перед** «Фрагменты базы знаний»; system prompt RAG дополнен одной фразой, что инструкции не заменяют факты из фрагментов.
- Ответ **`POST /knowledge/ask`**: поле **`applied_rule_ids`** (UUID применённых правил); при пустом retrieval (без вызова chat completion) — `[]`.
- **Не** затрагивается Memoh, сводки, SLA, project digest, Studio Admin UI.

## Фаза 11a — Assistant rules: хранение и аудит без LLM (выполнено)

- Правила (`studio_assistant_rules`): scope **`global`** (без FK), **`project`** (`project_id` обязателен), **`chat`** (`chat_id` обязателен, `project_id` null); статусы **`active`** / **`disabled`**; источники **`manual`** / **`control_group`**; опционально `created_by_telegram_user_id`, `created_from_message_id`, `metadata_json`.
- Аудит (`studio_assistant_rule_audit`): действия **`created`**, **`updated`**, **`disabled`**; `payload_json` без секретов; `rule_id` **SET NULL** при удалении правила (в 11a удаления нет — только disable).
- API только под **`STUDIO_ADMIN_TOKEN`** (как `/projects`, `/knowledge` при заданном токене); **без** вызова Memoh и **без** chat completion в самой фазе 11a; применение к KB RAG — **фаза 11b**.
- Команды **`/rule_*`**: только active control group, тот же ACL **`STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS`**, ответы только `sendMessage` в CG.

