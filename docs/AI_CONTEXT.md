# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 2a завершена** — Response Queue в Studio (модели, сервис, тесты) **без** Memoh и **без** Telegram. Дальше: **Фаза 2b / 3** — Celery/FastAPI-оболочка, Event Mirror (Фаза 4), затем интеграция с Memoh по варианту из [`docs/06_DECISIONS.md`](docs/06_DECISIONS.md).

## Текущая цель

Поднять Studio API + воркер, связать Event Mirror → `QueueService.enqueue`, выбрать и задокументировать вариант A/B/C перед любыми правками `internal/channel` / `telegram` в Memoh.

## Что уже работает

- Фазы 0–1: bootstrap, разведка Memoh (см. историю в `docs/04_PROJECT_LOG.md`).
- **Фаза 2a:** пакет [`studio/pb_studio/response_queue/`](studio/pb_studio/response_queue/) — таблицы `studio_response_turns` / `studio_inbound_messages`, статусы turn, debounce 2–4 с, per-chat блокировки + глобальный `sequence_number` для dispatch, дедуп по `dedupe_key`, `TurnProcessor`-контракт для воркера; 10 pytest-тестов.

## Что ещё не готово

- Подключение очереди к Telegram/Memoh runtime.
- Event Mirror, полноценный Studio API, Celery beat, RAG, SLA, админка.

## Последний стабильный commit

**Фаза 2a (очередь Studio):** `c4e382c22553f3b7b4fc5b2d46fec50240c3ea82` — сообщение `feat(studio): response queue core phase 2a`.

## Что изменилось в последней фазе

- Добавлен Python-пакет `pb_studio` под `studio/`, SQL-скелет миграции, обновлены docs и memory-bank.

## Изменённые файлы (Фаза 2a)

- `studio/pyproject.toml`, `studio/README.md`, `studio/pb_studio/**`, `studio/tests/**`, `studio/migrations/001_response_queue.sql`
- `docs/03_IMPLEMENTATION_PLAN.md`, `docs/06_DECISIONS.md`, `docs/07_RUNBOOK_WINDOWS.md`, `docs/AI_CONTEXT.md`, `docs/04_PROJECT_LOG.md`, `docs/05_CURRENT_TASK.md`, `memory-bank/activeContext.md`, `memory-bank/progress.md`

## Принятые решения

- Очередь ответов как **источник истины по turn** живёт в Studio DB до интеграции с Memoh.
- Memoh и Telegram adapter **не менялись** в 2a.
- Варианты интеграции A/B/C и рекомендация — в [`docs/06_DECISIONS.md`](docs/06_DECISIONS.md).

## Что нельзя трогать

- (как в Фазе 0.) Дополнительно до ADR: не патчить Memoh `telegram.go` / `inbound.go` без остановки и записи варианта в `docs/06_DECISIONS.md`.

## Следующая задача

- Фаза 3 (частично) или 2b: FastAPI `/queue/inbound`-стиль + Celery task, вызывающий `flush_due_turns` / `dispatch_next`; подготовка Event Mirror (Фаза 4).

## Вопросы к GPT

- нет
