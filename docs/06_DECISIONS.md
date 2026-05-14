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
