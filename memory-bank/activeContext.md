# Active context

**Сейчас:** **VPS 148.253.209.54** — NL turn isolation **выкатан** (2026-05-15): репо HEAD **`e0e75fd`** (`git reset --hard origin/pb-studio/main`); Studio **api/worker/beat** и **Memoh server** пересобраны и **up**; volumes Postgres/Redis **не трогались**; токены **не менялись**. Проверки: **jar `/health`**, **memo `/health`**, контейнеры **healthy/up**; **getMe** → **jarvispbweb_bot**, **webhook пустой**, **pending_update_count=0**; **vps-e2e-smoke** — **PASS** (SKIP: history, telegram live, pytest в prod-образе). **Живой сценарий «4 вопроса подряд»** (чаты → отчёт → запомни → модель) — **ждёт оператора**; после сообщений — сверка `studio_nl_interactions` / логов на отдельные turn и отсутствие смешивания.

**Ссылки:** Studio Admin **https://jar.pb-web.ru/admin/** · Memoh Web **https://memo.pb-web.ru**

**Следующий шаг:** в control group отправить очередь из плана (чаты / отчёт / запомни / модель), затем при **PASS** — краткая запись в `docs/04_PROJECT_LOG.md`; при **FAIL** — логи worker + строки NL из БД.
