# Главный гид pb-memoh-studio

## Что это

Один Telegram-ассистент студии поверх **Memoh** (агентное ядро) и **Studio Layer** (данные, RAG, SLA, очереди, аудит). Снаружи — один бот.

## Источник истины

Перед работой читай:

- `docs/AI_CONTEXT.md`
- `docs/04_PROJECT_LOG.md`
- `docs/05_CURRENT_TASK.md`
- `docs/06_DECISIONS.md`
- `memory-bank/activeContext.md`, `systemPatterns.md`, `techContext.md`

Длинный чат — не источник истины.

## Фазы

Работа идёт фазами (см. `docs/03_IMPLEMENTATION_PLAN.md`). Одна фаза — один понятный результат — один коммит (по возможности). Продуктовые фичи после Фазы 0–1.

## Секреты и локальная среда

- Шаблон переменных: `.env.example`.
- Реальные значения — только в **`.env.local`** (файл не коммитится).
- Агент может открыть `.env.local` в редакторе и перечислить поля для заполнения; пользователь вставляет ключи вручную.

## Что пользователь делает сам

- Создаёт бота в BotFather и копирует `TELEGRAM_BOT_TOKEN`.
- Включает/отключает privacy mode по инструкции `docs/10_TELEGRAM_SETUP.md`.
- Добавляет бота в тестовые и управляющую группы.
- Подтверждает approval в Cursor, если IDE спросит.
- Деплой на VPS — только после явного согласия (см. `docs/08_RUNBOOK_VPS.md`).

## Git

- `upstream` — [memohai/Memoh](https://github.com/memohai/Memoh).
- `origin` — [pbweb-studio/pb-memoh-studio](https://github.com/pbweb-studio/pb-memoh-studio).
- Тег `stable-upstream-memoh` — снимок чистого upstream до слоя студии.

## Запуск локальной инфраструктуры студии

```bash
docker compose -f docker-compose.local.yml up -d
```

Штатный `docker-compose.yml` в корне относится к Memoh и **не ломается**; инфраструктура Studio (Postgres 16 + pgvector, Redis) — в отдельном файле (см. `docs/06_DECISIONS.md`).
