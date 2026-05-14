# Active context

**Сейчас:** фаза **6d** в Studio — доставка готовых сводок (`generated`) в Telegram control group: `summary_delivery.py`, поля `delivery_*`, `POST /summaries/{id}/deliver-control-group`, `POST /summaries/deliver-pending`, Celery `deliver_pending_chat_summaries`; флаги `STUDIO_SUMMARY_DELIVERY_*` в compose для api/worker. Только `sendMessage`, тот же бот. Без Memoh, без LLM/RAG.

**Ветка:** `pb-studio/main`.

**Memoh:** не менялся в 6d.

**Следующий шаг:** фаза **6+** только по отдельной постановке.
