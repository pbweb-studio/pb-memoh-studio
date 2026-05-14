# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

Фаза 0 завершена → **Фаза 1: техническая разведка** (без правок ядра Memoh).

## Текущая цель

Найти в коде Memoh: приём Telegram updates, путь inbound-сообщений, MCP, причину поведения с реакцией «глазик»; зафиксировать план минимальной интеграции Response Queue в `docs/03_IMPLEMENTATION_PLAN.md`.

## Что уже работает

- Клонирован upstream Memoh, настроены remotes (`upstream` / `origin`), ветка `pb-studio/main`, тег `stable-upstream-memoh`.
- Каркас каталогов `studio/`, стартовый комплект `docs/`, Memory Bank, Cursor Rules, `.env.example`, `.cursorignore`.
- Отдельный `docker-compose.local.yml` для Postgres 16 + pgvector и Redis (инфраструктура Studio).
- Скелет `docker-compose.prod.yml` (без реального деплоя).

## Что ещё не готово

- Реализация Studio API, worker, Celery, Alembic, MCP-инструментов.
- Event Mirror, Response Queue, управляющая группа, сводки, SLA, RAG, импорт истории, полноценный Studio Admin.
- Интеграция Memoh ↔ Studio в runtime.

## Последний стабильный commit

Ветка `pb-studio/main`; сообщение: `chore(repo): bootstrap studio scaffold and docs`. Актуальный hash смотрите командой `git rev-parse HEAD` (в файле не дублируется, чтобы не расходилось с историей при amend).

## Что изменилось в последней фазе

- Bootstrap репозитория: слой студии поверх Memoh без изменения продуктовой логики Memoh.
- Добавлены документация, memory bank, правила Cursor, пример env, compose для локальной БД/Redis студии.

## Изменённые файлы (Фаза 0)

- `studio/**` (каркас)
- `docs/**`, `memory-bank/**`, `.cursor/rules/**`
- `.env.example`, `.cursorignore`, `docker-compose.local.yml`, `docker-compose.prod.yml`

## Принятые решения

- Один Telegram-бот.
- Системные уведомления только в управляющую группу (если не настроена — только логирование в Studio Layer).
- Memoh не используем как базу бизнес-данных.
- SLA не через heartbeat Memoh; отдельный монитор.
- Бизнес-логика и данные — в Studio Layer; связь с Memoh через MCP/API.
- Telegram events — Event Mirror в Studio.
- Быстрые сообщения — Response Queue (после разведки в Фазе 1–2).
- `origin` = [pbweb-studio/pb-memoh-studio](https://github.com/pbweb-studio/pb-memoh-studio), `upstream` = memohai/Memoh.

## Что нельзя трогать

- Не создавать второго Telegram-бота.
- Не кастомить heartbeat Memoh под бизнес-логику.
- Не делать Telegram App на раннем этапе.
- Не хардкодить документы в промпт.
- Не использовать memory Memoh как БД.
- Не менять ядро Memoh без записи в `docs/06_DECISIONS.md` и явной необходимости.

## Следующая задача

- Фаза 1: разведка Memoh (Telegram adapter, inbound, MCP, «глазик»); обновить `docs/03_IMPLEMENTATION_PLAN.md`, `docs/AI_CONTEXT.md`, логи и memory bank.

## Вопросы к GPT

- нет
