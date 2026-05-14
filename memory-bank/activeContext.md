# Active context

**Сейчас:** фаза **5b** в Studio — исходящая доставка `studio_system_notifications` в Telegram control group через Bot API `sendMessage` (тот же `TELEGRAM_BOT_TOKEN`), Celery `deliver_pending_system_notifications`, админ-роуты `GET/POST /notifications/system*`, Alembic `004`. Локальный `docker-compose.local.yml` пробрасывает переменные 5b в `studio-api` и `studio-worker`. Без polling/webhook из Studio.

**Ветка:** `pb-studio/main`.

**Memoh:** не менялся в 5b.

**Следующий шаг:** фаза 6 (сводки) по отдельной постановке.
