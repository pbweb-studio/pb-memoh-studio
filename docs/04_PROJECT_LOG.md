# Журнал проекта

## 2026-05-14 — Фаза 0 (Bootstrap)

- Статус: завершена.
- Клонирован upstream Memoh; remotes: `upstream` = memohai/Memoh, `origin` = pbweb-studio/pb-memoh-studio; ветка `pb-studio/main`; тег `stable-upstream-memoh`.
- Добавлены каркас `studio/`, документация `docs/`, Memory Bank, Cursor Rules, `.env.example`, `.cursorignore`, `docker-compose.local.yml` (Postgres16+pgvector, Redis), скелет `docker-compose.prod.yml`.
- Продуктовая логика Memoh не менялась.
- Стабильный коммит фазы 0: ветка `pb-studio/main`, сообщение `chore(repo): bootstrap studio scaffold and docs` (hash: `git rev-parse HEAD`).

## 2026-05-14 — Фаза 1 (разведка Memoh)

- Статус: завершена; код Memoh не изменялся.
- Задокументированы: Telegram adapter (`internal/channel/adapters/telegram/telegram.go`), inbound через `internal/channel/inbound.go` (очередь + воркеры) → `internal/channel/inbound/channel.go` (`HandleInbound`, `RouteDispatcher`, `sendModeConfirmation` / 👀), MCP (`internal/mcp`, `internal/workspace`, `internal/agent/tools`).
- Варианты Response Queue: [`docs/06_DECISIONS.md`](docs/06_DECISIONS.md). Детали трассировки: [`docs/03_IMPLEMENTATION_PLAN.md`](docs/03_IMPLEMENTATION_PLAN.md).
- Коммит: `4a42646617a7f632b9fc8d5c84e57dd45026052d`.

## 2026-05-14 — Фаза 2a (Response Queue в Studio)

- Статус: завершена (безопасная часть); Memoh / Telegram не менялись.
- Добавлены `studio/pb_studio/response_queue` (SQLAlchemy модели, `QueueService`, Pydantic-контракт, pytest), `studio/migrations/001_response_queue.sql`, обновлены `docs/*`, memory-bank.
- Коммит: `c4e382c22553f3b7b4fc5b2d46fec50240c3ea82`.
