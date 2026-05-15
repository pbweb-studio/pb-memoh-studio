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

## Фаза 12a — Импорт Telegram Desktop JSON в Event Mirror (выполнено)

- Включение: **`STUDIO_HISTORY_IMPORT_ENABLED=true`** при **`STUDIO_ADMIN_TOKEN`**; лимит размера файла **`STUDIO_HISTORY_IMPORT_MAX_BYTES`** (минимум 64 B в валидации Settings; по умолчанию 50 MiB).
- Импорт: **`POST /history-import/telegram-json`** (multipart `file` = JSON экспорта); синхронная обработка в API; job в **`studio_history_import_jobs`** со статусами **`pending`** / **`processing`** / **`completed`** / **`failed`** (на практике создаётся в **`processing`** и завершается в том же запросе).
- Данные: **`studio_chats`** (upsert по `telegram_chat_id`), **`studio_messages`** с **`raw_update_id = null`** и `raw_message` в форме, совместимой с потребителями зеркала (`message_id`, `date`, `chat`, опционально `from`, `text`/`caption`, вложенный фрагмент экспорта под **`studio_history_import`**); **`studio_telegram_users`** при наличии `from`; **`studio_chat_lifecycle_events`** для сообщений типа **`service`** (без `TelegramRawUpdate`).
- **Без** Memoh, Telegram Bot API, polling/webhook Studio, LLM/RAG/embeddings, Studio Admin UI, исходящих сообщений в Telegram.

## Фаза 13a — Studio Admin UI skeleton (выполнено)

- Доступ к **`/admin/*`** (кроме `GET /admin/login` для формы входа) только при заданном **`STUDIO_ADMIN_TOKEN`** в env: **503**, если токен не настроен.
- Клиент: **`Authorization: Bearer <STUDIO_ADMIN_TOKEN>`** или подписанная cookie после **`POST /admin/login`** (`admin_token` в форме); сервер не логирует значение токена.
- HTML без валидной авторизации: **302** на `/admin/login` (параметр `next`); не-HTML **Accept** (например только `application/json`) без Bearer — **401**.
- Контент **read-only** (таблицы и счётчики из БД); **без** изменений Memoh, бота, LLM/RAG; `POST /admin/logout` — сброс cookie.

## Фаза 13b — Studio Admin UI: детали и формы (выполнено)

- Те же **`STUDIO_ADMIN_TOKEN`** / cookie-сессия для **всех** POST под `/admin/*`; сообщения об успехе/ошибке через query **`fs`** / **`fe`** (URL-encoded, без секретов); валидация через Pydantic/`ValueError` → читаемый flash.
- Операции только через существующие сервисы: роль чата, проект create/archive, bind/unbind, правила create/disable, SLA ack/resolve, KB upload (при **`STUDIO_KB_ENABLED`**).

## Фаза 13c — Studio Admin UI: polish + usability (выполнено)

- Списки: GET-параметры фильтров и **`page` / `limit`** (пагинация без безлимитных выборок); общий helper URL для prev/next; пустые состояния и повтор панели пагинации под таблицей при нескольких страницах.
- Layout: breadcrumbs, активный пункт sidebar, offcanvas-меню на `md` ниже, `h4` заголовки, `app.css` для компактных badges.
- **Без** новых сущностей и без изменений Memoh / бота / LLM-RAG.

## Фаза 14a — Production compose + базовый deploy/runbook (выполнено, без фактического деплоя)

- **`docker-compose.prod.yml`**: отдельные prod volumes; Postgres/Redis без публикуемых портов по умолчанию; `studio-api` с healthcheck на `GET /health`; полный набор `STUDIO_*` / `TELEGRAM_BOT_TOKEN` через подстановку из env-файла или значения по умолчанию для проверки `compose config`.
- **Секреты:** оператор копирует `.env.prod.example` → `.env.prod` (не в git); сильные пароли Postgres и **`STUDIO_ADMIN_TOKEN`** обязательны перед реальным prod.
- **Прокси/TLS:** только шаблон `deploy/caddy/Caddyfile.example`; реальные домены и сертификаты — вне автоматизма репозитория до согласования.
- **Бэкап:** скрипт дампа через `docker compose exec` + инструкция restore и примечание по volume KB в `deploy/BACKUP_RESTORE.md`.

## Фаза 14b — Deploy readiness (выполнено, без фактического деплоя)

- **`.env.prod.example`:** маркировка `[REQUIRED]` / `[optional]` / `[secret]`; секреты в шаблоне пустые; feature flags с комментариями о зависимостях.
- **Проверки перед стартом:** `deploy/scripts/validate_env_prod.py` (условные требования при включённых флагах); `deploy/scripts/smoke-prod.sh` после старта (`/health`, `/admin/login`, редирект `/admin/*`, опционально `GET /projects` с Bearer — токены не печатаются).
- **Бэкап/restore:** `restore-postgres.sh`, `backup-kb-volume.sh`; Postgres и KB volume документированы раздельно в `deploy/BACKUP_RESTORE.md`.
- **Runbook:** расширен `docs/08_RUNBOOK_PRODUCTION.md` (чеклист VPS → smoke, ручные шаги control group и `/kb_ask` при включённом KB+RAG).
- **Caddy:** только комментарии-заглушки (домен, email ACME, upstream); реальные домены не добавлялись.

## Фаза 14c — Первый staging/prod deploy jar.pb-web.ru (выполнено)

- **VPS / домен:** `148.253.209.54`, публично **https://jar.pb-web.ru** (Caddy reverse proxy на `127.0.0.1:8000`); каталог деплоя на сервере: `/opt/pb-studio/pb-memoh-studio`; `.env.prod` только на хосте (**chmod 600**), **не** в git.
- **Проверки:** `GET /health`, `/admin/login`, `deploy/scripts/smoke-prod.sh`, `deploy/scripts/backup-postgres.sh`. **Memoh** не изменялся.
- **Код на сервер:** синхронизация с локального дерева (`git archive`), т.к. удалённая ветка отставала по `docker-compose.prod.yml`.
- **Миграции (репо):** `f8dbd06e09f7b081733061ca1c6aefcf9b727afb` — в ревизии `006_summary_delivery_control_group` выполняется `ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)` до записи длинных revision id.
- **Инцидент безопасности (14c):** при запуске вспомогательного shell с **`set -x`** в лог попала команда **`export STUDIO_ADMIN_TOKEN=…`**; **токен ротирован** на VPS. **Правило:** deploy- и smoke-обвязки **не** запускать с **`bash -x` / `set -x`**, если в том же процессе экспортируются секреты; предпочитать **`set -eu`**. Детали и чеклист — `docs/08_RUNBOOK_PRODUCTION.md` (разделы C, F).

## MVP стабилизация — роли Memoh / Studio (зафиксировано)

- **Memoh** = live-агент: Telegram runtime, входящие updates, ответы ассистента (личка / mention / reply), провайдер LLM, Memoh memory, Memoh Web.
- **Studio** = бизнес source of truth: Event Mirror, архив, control group, slash-команды `/kb_*`, `/summary_*`, `/project_*`, `/rule_*`, KB/RAG, проекты, SLA, правила, Studio Admin.
- **Команды Studio** обрабатываются из зеркала сообщений control group; ответы — **только** `sendMessage` в активную control group (тот же `TELEGRAM_BOT_TOKEN`, без второго бота и без polling/webhook из Studio).
- **Парсинг команд в группах:** поддержка суффикса `@BotUserName` у первого токена (`/kb_help@bot` и т.д.).
- **`/kb_help`:** справка и строки статуса флагов KB/RAG доступны **даже при** `STUDIO_KB_ENABLED=false`; остальные `/kb_*` по-прежнему требуют включённого KB.
- **Memoh — ответы в группах:** поведение Telegram streaming как в upstream Memoh (`stream.go` / adapter); отдельные UX-правки `groupFinalOnly` сняты до отдельной задачи.
- **Celery beat:** в `pb_studio.celery_app` добавлен периодический запуск `pb_studio.worker.process_control_group_commands` (интервал `STUDIO_CONTROL_COMMANDS_INTERVAL_SECONDS`, по умолчанию 5 с); при `STUDIO_CONTROL_COMMANDS_ENABLED=false` задача остаётся no-op на стороне цикла команд.
- **Celery worker + async engine (май 2026):** `run_control_commands_standalone` в **`finally`** вызывает **`dispose_engine()`** (коммит **`7a4a8a10`**), иначе при повторных **`asyncio.run()`** в worker глобальный AsyncEngine остаётся на «старом» loop и даёт **`RuntimeError: ... different loop`**.
- **Studio Admin hotfix (май 2026):** **`GET /admin/assistant-rules`** отдавал **500** из‑за **`NameError`** (пропущенные импорты констант/сервиса правил в `admin_ui.py`); исправлено в **`8af1537d`** без смены URL и без изменения REST **`/assistant-rules*`**.

## NL Business & Learning Layer (история; conversational path архивирован 2026-05-15)

- **Сейчас (single-brain):** Memoh **не** вызывает Studio nl-gate в inbound; пакет **`internal/studio`** с `PostNLGate` удалён. Celery beat **никогда** не регистрирует `studio-process-nl-interactions`. Задача **`pb_studio.worker.process_nl_interactions`** и **`run_nl_interactions_standalone`** — мгновенный no-op с `reason=nl_responder_archived_single_brain` (совместимость имён задач). Alembic **`018_nl_status_widen_finalize_pending`**: колонка **`studio_nl_interactions.status`** → `VARCHAR(64)`; все строки со **`status='pending'`** → **`ignored_disabled_single_brain_migration`**, заполняются `last_error` и `processed_at`. Ответы пользователю в prod — **только** Memoh + **Studio MCP**; HTTP gate и код `pb_studio/nl/*` остаются опциональным legacy/debug при явном **`STUDIO_NL_COMMANDS_ENABLED=true`**.
- **Ранее (до архивации):** быстрый gate `POST /integrations/memoh/nl-gate`, alias-scan, Celery-обработка `pending`, `PostNLGate` в Memoh inbound (в т.ч. подавление ассистента при ошибке gate) — см. исторические коммиты и `docs/04_PROJECT_LOG.md`; схема таблиц прежняя, кроме длины `status`.

## Single-brain Memoh + Studio MCP (ADR, май 2026)

- **Цель:** один ответчик в Telegram — **Memoh**; Studio остаётся **backend** (Postgres, Event Mirror, KB, SLA, проекты, правила) и отдаётся ассистенту через **MCP** (`studio-mcp`), без второго «разговорного» контура NL.
- **Prod defaults:** `STUDIO_NL_COMMANDS_ENABLED=false`; Celery beat **никогда** не регистрирует `studio-process-nl-interactions` (даже при `true`); `POST /integrations/memoh/nl-gate` возвращает **403** при выключенном флаге (зависимость `verify_nl_gate_feature_enabled` после опционального Bearer).
- **Memoh:** **`PostNLGate`** и пакет **`internal/studio`** удалены; inbound не консультирует Studio перед ассистентом. Переменные `MEMOH_STUDIO_NL_GATE_*` в коде не используются (оставить пустыми в `.env`).
- **Event Mirror** (`STUDIO_EVENTS_URL` / ingest) **без изменений**, не смешивать с NL.
- **Studio MCP:** сервис **`studio-mcp`** в `docker-compose.prod.yml` (`python -m pb_studio.mcp_server`), порт **`STUDIO_MCP_LISTEN_PORT`** (default 8765), опциональный **`STUDIO_MCP_AUTH_TOKEN`** (Bearer); 11 инструментов `studio_*` в `pb_studio/mcp_tools/handlers.py` + регистрация в `pb_studio/mcp_server/asgi.py`.
- **Slash-команды vs MCP-only (prod):** оператор выбирает **`STUDIO_CONTROL_COMMANDS_ENABLED`**. Рекомендация для минимизации дублей с Memoh: **`false`** (только MCP + при необходимости ручные операции в Studio Admin); **emergency:** оставить `true` и задокументировать риск параллельных ответов Studio slash и Memoh в CG. Event Mirror от slash **не** зависит.

### Откат single-brain

1. Откатить коммиты Memoh/Studio до состояния с `PostNLGate` и рабочим NL beat (или задеплоить предыдущие образы); восстановить **`MEMOH_STUDIO_NL_GATE_*`** и **`STUDIO_NL_*`** по старому runbook.
2. При откате миграции **`018`**: вручную осознанно (из бэкапа) вернуть строки `studio_nl_interactions`, помеченные как **`ignored_disabled_single_brain_migration`**, если нужен повторный прогон NL worker.
3. Остановить **`studio-mcp`** или убрать MCP-подключение в Memoh Admin, если откатываетесь полностью на NL+gate.

## Memoh DM history hygiene (orphan watchdog + skill anti-coalescing, 2026-05-15)

**Контекст.** В DM с ботом «ИИ Purple Bear» 2026-05-15 пользователь увидел два связанных симптома: (1) кажущееся off-by-one — бот «отвечал на N-1»; (2) паразитный хвост вида «Вижу: личку с тобой, группу Управление Jarvis, группу PBVOICE» в каждом ответе. Диагностика на VPS (`memoh-jar-postgres-1`) показала, что **orphan user-row отсутствует**, все user/assistant пары в сессии `cf704360-…` шли подряд (timestamps интервал ~2 мс). Корневая причина другая:

1. **Сессия DM ни разу не сбрасывалась 2 дня (114 строк подряд).** Memoh пихал в каждый промпт большую долю истории.
2. **Галлюцинация имён.** Один раз модель вызвала `get_contacts`, получила список с `target=-1003903704506` (без `chat.title`), и галлюцинировала имена «Управление Jarvis», «PBVOICE». Потом начала **копировать собственную преамбулу «Вижу: …»** в каждый следующий ответ как шаблон.
3. **Склейка ответов.** На вопрос «как меня зовут?» модель отвечала «Кратко за сегодня: …\n\nТебя зовут Денис Губанов.» — реальный ответ был, но прятался ниже повторённого вчерашнего отчёта. Пользователь видел только верх и фиксировал «off-by-one».
4. **Отдельно:** хронический `getUpdates context deadline exceeded` в Telegram polling Memoh идёт постоянно (long-poll таймауты, ~раз в 30 с) и **в редких случаях** действительно может оставить orphan user-row, если Memoh не успел дописать ассистент-ответ из-за обрыва. Это вторичный, но реальный риск, см. инцидент 2026-05-15 ~21:25 MSK с `source_message_id=703`.

**Решение (без правок Memoh-core, в духе `040-no-core-damage.mdc`):**

1. **Скиповать «Вижу: …» преамбулу.** В `skills/pb-studio-manager/SKILL.md` добавлен раздел «Анти-галлюцинации и анти-склейка ответов»: запрещён список чатов как преамбула, запрещено выдумывать названия групп без источника (`get_contacts` / `studio_list_chats` / `studio_get_chat_context`), запрещено пересказывать ранее сказанное без явной просьбы, требование «один вопрос — один ответ».
2. **Watchdog против orphan user-row.** Скрипт `deploy/scripts/memoh-orphan-cleanup.sh` + systemd unit `deploy/systemd/memoh-orphan-cleanup.{service,timer}` раз в 60 с удаляют из `bot_history_messages` user-row старше `GRACE_SECONDS=120`, у которых в той же `session_id` нет assistant/tool строки с `created_at >= user.created_at`. Скрипт идемпотентен и трогает только Memoh-Postgres (`memoh-jar-postgres-1`). Установка — симлинком в `/etc/systemd/system/`, см. `deploy/systemd/README.md`.
3. **Immediate relief.** Грязная DM-сессия `cf704360-dfe6-45e4-8999-e22163a34138` помечена `deleted_at = now()` и её 114 строк `bot_history_messages` удалены (бэкап в `/opt/pb-studio/backups/memoh-dm-reset/dm_cf704360-…_full_tables.sql` + `_history.csv` + `_session.csv`). Следующее сообщение пользователя в DM создаст новую сессию.

**Отказ от core-патча.** Правка Memoh-core (retry assistant-row при сбое генерации, soft-fail вместо orphan, авто-компакция длинных DM сессий) откладывается в **PR2**. Ждём, что watchdog + skill hygiene удержат поведение бота. Если повторятся — открываем отдельный ADR на core-патч (по правилу `040-no-core-damage.mdc` — только с явной записью).

**Откат:**
- Skill: вернуть прежнюю версию `skills/pb-studio-manager/SKILL.md` из git и скопировать в `/opt/memoh/data/skills/pb-studio-manager/SKILL.md` контейнера `memoh-jar-server-1`, перезапустить контейнер.
- Watchdog: `systemctl disable --now memoh-orphan-cleanup.timer && rm /etc/systemd/system/memoh-orphan-cleanup.{service,timer} && systemctl daemon-reload`.
- Backup-восстановление сессии: бэкап-файлы в `/opt/pb-studio/backups/memoh-dm-reset/`, `psql -U memoh -d memoh -f dm_cf704360-…_full_tables.sql` (но смысла мало: история была компрометирована).

