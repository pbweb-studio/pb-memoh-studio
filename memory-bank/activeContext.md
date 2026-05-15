# Active context

**Сейчас:** VPS **148.253.209.54** — выкат **`566052e1`** (NL worker `FOR UPDATE`/`SKIP LOCKED`, логи `nl_reply_sent`, Memoh suppress при ошибке `PostNLGate`). Smoke **PASS**. **Дальше:** оператор — 4 фразы в CG + `/kb_help` + при необходимости getMe/webhook; повторный `studio/scripts/diag_last_nl_interactions.sql`.

**Ссылки:** **https://jar.pb-web.ru/admin/** · **https://memo.pb-web.ru**

**Следующий шаг:** ручная приёмка из `docs/04_PROJECT_LOG.md` (блок 2026-05-15 NL anti–off-by-one); при **PASS** — короткая строка в журнал; при **FAIL** — логи worker + SQL.
