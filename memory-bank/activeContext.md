# Active context

**Сейчас:** фаза **4b** выполнена по **варианту C** — асинхронное зеркалирование сырого Telegram `Update` из [`internal/channel/adapters/telegram/telegram.go`](internal/channel/adapters/telegram/telegram.go) в Studio (`STUDIO_EVENTS_URL`), модуль [`internal/channel/adapters/telegram/studio_event_mirror.go`](internal/channel/adapters/telegram/studio_event_mirror.go), тесты `studio_event_mirror_test.go`. По умолчанию выключено (`MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED=false`).

**Ветка:** `pb-studio/main`.

**Блокеры:** нет.

**Следующий безопасный шаг:** e2e-проверка с реальным или тестовым ботом при поднятом `studio-api` и заполненных env; затем планирование фазы 5+.
