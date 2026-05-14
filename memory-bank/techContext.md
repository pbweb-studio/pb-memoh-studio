# Tech context

- **Memoh:** upstream в этом репо; Docker compose upstream в `docker-compose.yml` (не ломать без решения).
- **Studio (план):** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, httpx, OpenAI SDK; Celery + Redis; MCP (Python MCP SDK / FastMCP); админка Jinja2 + HTMX + Bootstrap.
- **DB:** PostgreSQL 16 + pgvector для студии (локально через `docker-compose.local.yml`).
- **Локально:** Windows, Docker Desktop.
- **Прод (позже):** VPS, Compose, Caddy, домен `memo.pb-web.ru`.

Ограничения: не React/Vue для первой админки; не второй бот; не отдельная vector DB, пока хватает pgvector.
