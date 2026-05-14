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

## Развилки (TBD)

- Точка **первого** контакта Studio→Memoh для turn (HTTP vs patch) — после готовности Event Mirror + воркера; варианты ниже.

## Фаза 2a — Response Queue в Studio (безопасная часть, выполнено)

- Реализация: [`studio/pb_studio/response_queue/`](studio/pb_studio/response_queue/), DDL-скелет [`studio/migrations/001_response_queue.sql`](studio/migrations/001_response_queue.sql), тесты [`studio/tests/test_response_queue.py`](studio/tests/test_response_queue.py).
- **Не делалось намеренно:** правки Memoh, Telegram adapter, реальный Telegram runtime, Celery wiring, FastAPI-роуты продукта (часть Фазы 3).
- **Рекомендация по интеграции (без изменения текста вариантов A/B/C):** по-прежнему склоняемся к **варианту C** (очередь и статусы в Studio + минимальный контракт в Memoh), пока не доказано, что gateway (A) дешевле по сопровождению. Окончательный выбор — после прототипа Event Mirror + одного E2E без продакшена.

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
