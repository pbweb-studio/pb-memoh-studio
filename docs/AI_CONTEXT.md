# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 4b (транспорт Memoh → Studio Event Mirror) — вариант C реализован.** Memoh по-прежнему получает Telegram `Update` как раньше; после дедупа `update_id` необязательно зеркалирует **сырой** JSON в `POST` на URL из `STUDIO_EVENTS_URL` (асинхронно, с коротким timeout). **Фаза 4a** (ingest в Studio) без изменений по смыслу.

## Текущая цель

Фаза **5 не открыта** до явного решения. Опционально: e2e Memoh + Studio с включённым зеркалом; иначе — планирование фазы 5 по отдельной задаче.

## Что уже работает

- Фазы 0–4a: см. `docs/04_PROJECT_LOG.md`.
- **4b:** зеркало в [`internal/channel/adapters/telegram/studio_event_mirror.go`](internal/channel/adapters/telegram/studio_event_mirror.go), вызов в [`internal/channel/adapters/telegram/telegram.go`](internal/channel/adapters/telegram/telegram.go).
- **Проверка 4b закрыта (CI в агенте):** Go-тесты пакета Telegram adapter прошли (`docker run … golang:1.25` → `go test ./internal/channel/adapters/telegram/... -count=1`, образ соответствует директиве `go` в `go.mod`); Studio — `pytest tests/ -v` в Docker `python:3.12-slim`, **32 passed**; `docker compose -f docker-compose.local.yml config` — без ошибок.
- Инжест и нормализация в Studio: `studio/pb_studio/event_mirror/`.
- Решение по интеграции: `docs/06_DECISIONS.md` (ADR A/B/C; для raw Update утверждён и закодирован **C**).

## Что ещё не готово

- Полный e2e «Telegram → Memoh → Studio БД» в прод-окружении (ручная проверка/наблюдаемость по желанию).
- Управляющая группа (Фаза 5), сводки, RAG, SLA, Studio Admin.

## Идентификаторы коммитов (фаза 4b)

- **Реализация Go-hook (feat telegram mirror, вариант C):** `67bc573d1b5891f6cf9d3613580f59ca92200ec9`
- **Коммит с записью результатов автоматической проверки 4b (доки + memory-bank):** `1c8f9f6c0ef1ec71e78c3dcc92879c8c3b8c2b42` (сообщение `docs: close phase 4b verification (tests documented)`).
- **Актуальный корень ветки** (если есть только doc-follow-up поверх): `git rev-parse HEAD`.

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

- По необходимости: e2e Memoh + `studio-api` и ingest в `studio_telegram_raw_updates`. Открытие **фазы 5** — только по явной постановке (не начинать самовольно).

## Вопросы к GPT

- нет
