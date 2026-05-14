# Active context

**Сейчас:** фаза **14c** + **VPS E2E smoke** — Studio на **148.253.209.54**, **https://jar.pb-web.ru**; checkout VPS **= `origin/pb-studio/main`**; прогон **`vps-e2e-smoke.sh`** — **PASS** с ожидаемыми **SKIP** (RAG/chat key, Telegram-токен, history import off, pytest не в prod-образе). **Memoh не менялся.** `.env.prod` только на сервере (не в git). Миграции: якорь **`f8dbd06e09f7b081733061ca1c6aefcf9b727afb`**. Инцидент `set -x` / токен — см. `docs/08`, `docs/06`.

**Ветка:** `pb-studio/main`.

**Следующий шаг:** секреты/флаги на VPS по продукту (при необходимости), **6+** / **13+** / **10+** — по постановке.
