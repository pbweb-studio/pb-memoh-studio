# Studio Layer (Python)

Пакет **`pb_studio`** — слой студии поверх Memoh. Фаза 2 (безопасная часть): **Response Queue** без интеграции в Telegram и без изменений ядра Memoh.

## Установка (разработка)

```bash
cd studio
python -m pip install -e ".[api,dev]"
pytest
```

## Response Queue

- Модели: `pb_studio.response_queue.models`
- Логика: `pb_studio.response_queue.service.QueueService`
- Статусы: `pb_studio.response_queue.statuses`

Минимальный HTTP-слой (только контракт, не связан с Memoh): `pb_studio.api.queue_routes` — префикс `/queue`.
