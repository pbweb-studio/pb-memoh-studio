# Решения и зафиксированные варианты

## Git / репозитории

- **`upstream`**: https://github.com/memohai/Memoh.git — эталон Memoh.
- **`origin`**: https://github.com/pbweb-studio/pb-memoh-studio.git — рабочий репозиторий студии (создан вручную).
- Рабочая ветка: **`pb-studio/main`**.
- Тег **`stable-upstream-memoh`**: аннотированный снимок upstream до студийных коммитов.

## Продукт / платформа

- Один Telegram-бот; второй бот не вводим.
- Системные уведомления только в **управляющую группу**; если не настроена — только лог в Studio Layer.
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

## ADR — Telegram / Memoh → Studio Event Mirror (`POST /events/telegram`) перед фазой 4b

**Статус:** зафиксировано в документации только; **код Memoh и Telegram adapter не менялись**. Реализация транспорта (4b+) — после явного выбора варианта ниже (или пилота по «запасному» пути).

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
