# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 4b (транспорт Memoh → Studio Event Mirror) — вариант C реализован.** Memoh по-прежнему получает Telegram `Update` как раньше; после дедупа `update_id` необязательно зеркалирует **сырой** JSON в `POST` на URL из `STUDIO_EVENTS_URL` (асинхронно, с коротким timeout). **Фаза 4a** (ingest в Studio) без изменений по смыслу.

## Текущая цель

Следующие шаги продукта: e2e-проверка Memoh + Studio с включённым зеркалом, затем фазы 5+ (управляющая группа, сводки, RAG и т.д.) по плану.

## Что уже работает

- Фазы 0–4a: см. `docs/04_PROJECT_LOG.md`.
- **4b:** зеркало в [`internal/channel/adapters/telegram/studio_event_mirror.go`](internal/channel/adapters/telegram/studio_event_mirror.go), вызов в [`internal/channel/adapters/telegram/telegram.go`](internal/channel/adapters/telegram/telegram.go).
- Инжест и нормализация в Studio: `studio/pb_studio/event_mirror/`.
- Решение по интеграции: `docs/06_DECISIONS.md` (ADR A/B/C; для raw Update утверждён и закодирован **C**).

## Что ещё не готово

- Полный e2e «Telegram → Memoh → Studio БД» в прод-окружении (ручная проверка/наблюдаемость по желанию).
- Управляющая группа (Фаза 5), сводки, RAG, SLA, Studio Admin.

## Идентификатор коммита фазы 4b

- **Текущий корень ветки** (полный SHA): `git rev-parse HEAD` на `pb-studio/main`.
- **Коммит с реализацией** (сообщение `feat(telegram): memoh studio event mirror hook phase 4b variant C`): `git log --grep='memoh studio event mirror hook phase 4b variant C' -1 --format=%H` (при нескольких совпадениях возьмите последний по дате).

**Код Event Mirror Studio (фаза 4a, исторический якорь):** `eb0bdcd94699215118cd9aee41b5827453c21b7f`

**Документация ADR (только текст, перед кодом 4b):** `60a319773fc545be147a29625e3121613002bd7f` — если отличается от HEAD с реализацией 4b, это **отдельный** коммит (тело ADR без Go-изменений).

## Файлы Memoh, изменённые в фазе 4b (вариант C)

1. [`internal/channel/adapters/telegram/telegram.go`](internal/channel/adapters/telegram/telegram.go) — после успешного прохождения дедупа: `mirrorTelegramUpdateToStudioAsync(cfg.ID, u)`.
2. [`internal/channel/adapters/telegram/studio_event_mirror.go`](internal/channel/adapters/telegram/studio_event_mirror.go) — новый модуль: POST, env, timeout, Bearer, `recover` в горутине.
3. [`internal/channel/adapters/telegram/studio_event_mirror_test.go`](internal/channel/adapters/telegram/studio_event_mirror_test.go) — тесты зеркала.

`inbound.go`, `dispatcher`, цикл polling/webhook **не** переписывались сверх минимальной вставки в адаптере.

## Принятые решения

- Один бот; второй Telegram-бот не вводится; Memoh не переводится на внешний gateway; схема владения getUpdates/webhook **не** менялась.
- Бизнес-логика и нормализация — в Studio; в Memoh только транспорт JSON.
- Response Queue в Studio **не** включается из Memoh; только существующий флаг `STUDIO_MIRROR_ENQUEUE_USER_MESSAGES` на стороне Studio.
- Зеркало выключается `MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED=false` (по умолчанию).

## Что нельзя трогать без нового ADR

- Не включать второй потребитель того же бота в обход согласованной схемы; не дублировать системные Telegram-уведомления из этого hook.

## Следующая задача

- Проверка в связке: Memoh + `studio-api`, ingest в `studio_telegram_raw_updates`, мониторинг логов `studio event mirror` при сбоях Studio.

## Вопросы к GPT

- нет
