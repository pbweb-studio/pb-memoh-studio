# Текущая задача

## После фазы 14c (staging jar.pb-web.ru)

**Статус:** Studio развёрнут на **148.253.209.54**, публично **https://jar.pb-web.ru**; проверены health, админка, `smoke-prod.sh`, бэкап Postgres. **Memoh не менялся.** `.env.prod` только на VPS (не в git). Документация 14c и инцидент `set -x` / ротация `STUDIO_ADMIN_TOKEN` — в `docs/08`, `docs/06`, `docs/AI_CONTEXT`, memory-bank.

**Следующий шаг:** донастройка секретов/флагов на VPS (Telegram, RAG при необходимости), **6+** / **13+** / **10+** — по постановке.
