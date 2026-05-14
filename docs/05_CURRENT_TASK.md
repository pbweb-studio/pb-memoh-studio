# Текущая задача

## После VPS E2E smoke (jar.pb-web.ru)

**Статус:** на **148.253.209.54** checkout **синхронизирован с `origin/pb-studio/main`**; прогон **`./deploy/scripts/vps-e2e-smoke.sh`** — **PASS** с ожидаемыми **SKIP**: RAG (нет chat key / выключен), Telegram (`TELEGRAM_BOT_TOKEN` пустой или control commands выключены), history import (флаг выключен), **pytest** в prod Docker-образе (модуля pytest нет — тесты в CI/dev). **Memoh не менялся.** `.env.prod` только на VPS (не в git, не печатать).

**Следующий шаг:** по продукту — донастройка секретов/флагов на VPS (при необходимости), **6+** / **13+** / **10+** — по отдельной постановке.
