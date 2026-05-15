# Active context

**Сейчас:** **VPS 148.253.209.54** — **`/opt/pb-studio/pb-memoh-studio`**, ветка **`origin/pb-studio/main`**, **HEAD `7a4a8a10`** (MVP **`e6e4a13f`** + docs **`8d2b41d3`** + Celery fix **`7a4a8a10`**). Выборочно пересобраны **memoh-jar `server`** и **studio-api / studio-worker / studio-beat**.

**Ссылки:** Studio Admin **https://jar.pb-web.ru/admin/** · Memoh Web **https://memo.pb-web.ru**

**Проверено на сервере:** **getMe** → **jarvispbweb_bot** / **ИИ Purple Bear**; **webhook пустой**; **pending_update_count=0**; **`GET /control-group`** — active, **Управление Jarvis**, **telegram_chat_id=-1003903704506**; в БД **485395885** — `chat_role=unknown` (не control group). В `studio_control_commands` есть **`kb_help` → processed** с ответом (история); вариант **`/kb_help@jarvispbweb_bot`** в БД пока **0 строк** — нужна ручная отправка.

**Security:** ротация **`TELEGRAM_BOT_TOKEN`** после возможной утечки в URL — **`USER_ACTION_REQUIRED`**, пока оператор явно не подтвердил.

**Ручные шаги в Telegram:** **`mvp-private-001 привет`** (личка); **`@jarvispbweb_bot mvp-group-mention-001 ты тут?`** (группа); **`/kb_help`** и **`/kb_help@jarvispbweb_bot`** (control group).

**Известная проблема вне MVP slash:** **`GET /admin/assistant-rules`** — **HTTP 500** (smoke FAIL на списке).

**Кодовые якоря:** Memoh **`b0e7b510`** (long poll + redaction); Studio control group UI **`dd285584`**; beat + парсер `@bot` + `/admin/control-commands` — в **`e6e4a13f`**.

**Следующий шаг:** выполнить ручные Telegram-проверки выше и при необходимости зафиксировать ротацию токена; отдельно — разбор **500** на **`/admin/assistant-rules`**.
