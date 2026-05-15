# Active context

**Сейчас:** зафиксирован **NL anti–off-by-one** (воркер: `FOR UPDATE` / Postgres `SKIP LOCKED` по одной `pending` строке за транзакцию; логи `source_update_id`, `nl_reply_sent`; Memoh: при ошибке/HTTP≠2xx `PostNLGate` — **Warn** + подавление ассистента). Диагностика БД: `studio/scripts/diag_last_nl_interactions.sql`.

**Деплой после merge:** **studio-api + studio-worker + studio-beat**; **Memoh server** (изменён `internal/channel/inbound/channel.go` + `internal/studio/nl_gate.go`). Оператор: живая приёмка 4 фраз в CG.

**Ссылки:** Studio Admin **https://jar.pb-web.ru/admin/** · Memoh Web **https://memo.pb-web.ru**

**Следующий шаг:** на VPS пересобрать сервисы выше; в control group — 4 фразы из плана; при **PASS** — строка в `docs/04_PROJECT_LOG.md`; при **FAIL** — `diag_last_nl_interactions.sql` + логи `nl_turn_*` / `nl_reply_sent`.
