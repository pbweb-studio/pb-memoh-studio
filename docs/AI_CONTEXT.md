# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 1 завершена** (разведка Memoh без правок кода). Следующая: **Фаза 2** — Response Queue в Studio + выбор интеграции с Memoh по [`docs/06_DECISIONS.md`](docs/06_DECISIONS.md).

## Текущая цель

Реализовать очередь Studio (per-chat, debounce, статусы) и зафиксировать контракт с Memoh (вариант A/B/C из решений).

## Что уже работает

- Фаза 0: каркас репо, docs, memory-bank, compose studio-infra.
- **Фаза 1:** карта кода Memoh для Telegram / inbound / MCP / реакции 👀 задокументирована в [`docs/03_IMPLEMENTATION_PLAN.md`](docs/03_IMPLEMENTATION_PLAN.md); варианты Response Queue — в [`docs/06_DECISIONS.md`](docs/06_DECISIONS.md).

## Что ещё не готово

- Studio API/worker/Celery, Event Mirror, Response Queue (runtime), MCP инструментов студии, остальные фазы.

## Последний стабильный commit

**Фаза 1 (разведка):** `PHASE1_RECON_HASH`

_В этом поле — полный hash коммита с результатами разведки (`docs/phase1`). Обновляется коммитом сразу после основного коммита фазы._

## Что изменилось в последней фазе

- Только документация: детальная разведка `internal/channel/adapters/telegram`, `internal/channel/inbound`, `RouteDispatcher`, MCP-слой, причина 👀.

## Изменённые файлы (Фаза 1)

- [`docs/03_IMPLEMENTATION_PLAN.md`](docs/03_IMPLEMENTATION_PLAN.md)
- [`docs/06_DECISIONS.md`](docs/06_DECISIONS.md)
- [`docs/AI_CONTEXT.md`](docs/AI_CONTEXT.md)
- [`docs/04_PROJECT_LOG.md`](docs/04_PROJECT_LOG.md)
- [`docs/05_CURRENT_TASK.md`](docs/05_CURRENT_TASK.md)
- [`memory-bank/activeContext.md`](memory-bank/activeContext.md)
- [`memory-bank/progress.md`](memory-bank/progress.md)

## Принятые решения

- (без изменений относительно Фазы 0; добавлены варианты A/B/C для очереди — см. `docs/06_DECISIONS.md`.)

## Что нельзя трогать

- (как в Фазе 0.)

## Следующая задача

- Фаза 2: проектирование и реализация Response Queue в Studio; выбор варианта интеграции с Memoh; тесты.

## Вопросы к GPT

- нет
