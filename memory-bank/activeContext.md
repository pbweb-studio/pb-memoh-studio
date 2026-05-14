# Active context

**Сейчас:** фаза **14c** — Studio **развёрнут** на VPS **148.253.209.54**, публично **https://jar.pb-web.ru**; health, админка, smoke, бэкап Postgres проверены. **Memoh не менялся.** `.env.prod` только на сервере (не в git). В репо: фикс миграции **`f8dbd06e09f7b081733061ca1c6aefcf9b727afb`**. Инцидент: `STUDIO_ADMIN_TOKEN` в лог из‑за `set -x` у обвязки — токен ротирован; правило задокументировано в `docs/08_RUNBOOK_PRODUCTION.md` и `docs/06_DECISIONS.md`.

**Ветка:** `pb-studio/main`.

**Следующий шаг:** секреты/флаги на VPS по продукту (Telegram, RAG при необходимости), **6+** / **13+** / **10+** — по постановке.
