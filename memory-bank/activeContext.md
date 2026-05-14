# Active context

**Сейчас:** фаза **6c** в Studio — продуктовый API сводок: `POST /summaries/chat/{uuid}/today|yesterday|period`, `GET .../latest` под `STUDIO_ADMIN_TOKEN`; логика `summaries/product.py` (планировщик + шаблонная генерация 6b); периоды today/yesterday в UTC. В `docker-compose.local.yml` для `studio-api` и `studio-worker` проброшены `STUDIO_SUMMARY_*`. Без внешнего LLM, без Telegram send для сводок.

**Ветка:** `pb-studio/main`.

**Memoh:** не менялся в 6c.

**Следующий шаг:** фаза **6+** только по отдельной постановке (LLM и/или доставка сводок).
