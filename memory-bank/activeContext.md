# Active context

**Сейчас:** **VPS 148.253.209.54** — **`/opt/pb-studio/pb-memoh-studio`**, ветка **`origin/pb-studio/main`**, **HEAD `7a4a8a10`** (MVP **`e6e4a13f`** + docs **`8d2b41d3`** + Celery fix **`7a4a8a10`**). Выборочно пересобраны **memoh-jar `server`** и **studio-api / studio-worker / studio-beat**.

**Ссылки:** Studio Admin **https://jar.pb-web.ru/admin/** · Memoh Web **https://memo.pb-web.ru**

**Проверено на сервере:** **getMe** → **jarvispbweb_bot** / **ИИ Purple Bear**; **webhook пустой**; **pending_update_count=0**; **`GET /control-group`** — active, **Управление Jarvis**, **telegram_chat_id=-1003903704506**; в БД **485395885** — `chat_role=unknown` (не control group). В Telegram (скрины оператора, **2026-05-14**): личка с **`mvp-private-001`**, **`/kb_help`** и **`/kb_help@jarvispbweb_bot`** в control group — ответы бота **ИИ Purple Bear** корректны.

**Security:** ротация **`TELEGRAM_BOT_TOKEN`** — оператор **отказался** (**2026-05-14**, согласовано); **остаточный риск принят**, пункт по ротации закрыт.

**Ручной шаг (опционально):** **`@jarvispbweb_bot mvp-group-mention-001 ты тут?`** в обычной группе — для полного маркера в `studio_messages`, если нужен E2E по группе.

**Известная проблема вне MVP slash:** **`GET /admin/assistant-rules`** — **HTTP 500** (smoke FAIL на списке).

**Кодовые якоря:** Memoh **`b0e7b510`** (long poll + redaction); Studio control group UI **`dd285584`**; beat + парсер `@bot` + `/admin/control-commands` — в **`e6e4a13f`**.

**Следующий шаг:** при необходимости — маркер в группе выше; отдельно — разбор **500** на **`/admin/assistant-rules`**.
