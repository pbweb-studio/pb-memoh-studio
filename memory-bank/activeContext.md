# Active context

**Сейчас:** **MVP-стабилизация** — коммит **`e6e4a13f`** в репо; роли Memoh vs Studio (`docs/15_OPERATOR_GUIDE.md`, `docs/06_DECISIONS.md`). Studio **148.253.209.54** / **https://jar.pb-web.ru/admin/**; Memoh Web **https://memo.pb-web.ru**; репо на VPS **`/opt/pb-studio/pb-memoh-studio`**, ветка **`origin/pb-studio/main`**.

- **Memoh:** `b0e7b510` — long poll timeout + redaction URL с токеном; группы — final-only send по умолчанию (`MEMOH_TELEGRAM_GROUP_STREAMING_ENABLED`).
- **Studio:** `dd285584` — control group в админке; beat **`process_control_group_commands`**; **`STUDIO_CONTROL_COMMANDS_INTERVAL_SECONDS`**; `/kb_help` при выключенном KB; парсер `/cmd@bot`; **`/admin/control-commands`**.

**Security:** ротация **`TELEGRAM_BOT_TOKEN`** после возможной утечки — **подтвердить оператором**; до подтверждения — **USER_ACTION_REQUIRED**.

**Ветка:** `pb-studio/main`.

**Следующий шаг:** приёмка на VPS (один Memoh poller, private + group mention, `/kb_help` + `/kb_help@bot`, mirror rows); при необходимости деплой только memoh-jar server и studio-api/worker/beat без full stack.
