# Руководство оператора PB Memoh Studio

Коротко: **один Telegram-бот**. **Memoh** владеет входящим потоком и обычным диалогом. **Studio** — зеркало, архив, slash-команды и бизнес-данные.

## 1. Что делает Memoh

- **Telegram runtime:** long polling / webhook (в проде VPS — Memoh; Studio **не** вызывает `getUpdates` и **не** ставит webhook).
- **Получение updates** и маршрутизация в ассистента.
- **AI-ответы** на личку, mention и reply в группах (режим ассистента).
- **Провайдер/модель** (например OpenAI) — настройки Memoh / канала.
- **Конфиг бота** Memoh, credentials каналов, Memoh memory (память агента).
- **Memoh Web UI** — пользовательский интерфейс Memoh: **https://memo.pb-web.ru** (на текущем контуре).

## 2. Что делает Studio

- **Event Mirror:** приём событий от Memoh → `studio_messages`, сырые updates, аудит.
- **Архив** чатов и сообщений студии.
- **Control group:** одна активная «управляющая» Telegram-группа; системные ответы Studio только туда.
- **Slash-команды** из control group: `/kb_*`, `/summary_*`, `/project_*`, `/rule_*` — обрабатываются Studio (не Memoh LLM).
- **KB / RAG**, **проекты**, **SLA**, **правила ассистента** — хранение и логика в БД Studio.
- **Studio Admin:** **https://jar.pb-web.ru/admin/** — назначение control group, просмотр чатов, KB, правил, SLA, **журнал команд** `/admin/control-commands`.

## 3. Что не дублируется

| Memoh memory | Studio DB |
|--------------|-----------|
| Память агента в разговоре | Бизнес-источник правды студии |

Проекты, KB, SLA, правила, роли чатов, привязки проектов — **только Studio**. Memoh не превращают в CRM студии.

## 4. Режимы в Telegram

| Сообщение | Кто отвечает |
|-----------|----------------|
| Обычный текст, mention бота, reply боту | **Memoh** (ассистент) |
| `/kb_*`, `/summary_*`, `/project_*`, `/rule_*` в **active control group** | **Studio** (command mode) |
| Системные ответы Studio (команды, уведомления, сводки при доставке) | **только** в active control group (`sendMessage`) |

В группах Telegram часто добавляет суффикс `@имя_бота` к команде. Studio нормализует это к той же команде (например `/kb_help@bot` → `/kb_help`).

## 5. Что делать пользователю

1. **Открыть Memoh (чат с ботом / mention):** **https://memo.pb-web.ru** и Telegram.
2. **Открыть Studio Admin:** **https://jar.pb-web.ru/admin/** (логин по cookie после POST `/admin/login`).
3. **Назначить control group:** `/admin/control-group` → выбрать group/supergroup из зеркала → «Сохранить».
4. **Проверить команды:** в управляющей группе отправить `/kb_help`; статусы и кнопка «Обработать pending» — **`/admin/control-commands`**.
5. **Флаги на сервере** (без публикации значений): `STUDIO_CONTROL_COMMANDS_ENABLED=true`, `TELEGRAM_BOT_TOKEN` задан для Studio worker/api (тот же токен, что у Memoh), при необходимости `STUDIO_KB_ENABLED` для операций KB кроме справки `/kb_help` (справка работает и при выключенном KB).

## 6. Smoke-данные на Overview

В админке на обзоре могут отображаться несколько проектов / KB / правил из автоматических smoke-тестов или ручных прогонов. Это **не** обязательно реальные клиентские сущности. Удаление или архивация — только осознанно (через админку/API), отдельным запросом; скрипты очистки без подтверждения оператора не запускать.

## 7. Безопасность

- Не коммитить `.env.prod`, `.env.memoh`, `config.toml` с секретами.
- Не использовать `set -x` / `bash -x` рядом с `export` секретов.
- Если **TELEGRAM_BOT_TOKEN** когда-либо попал в лог или URL — **ротировать в BotFather** и обновить токен **и** в Memoh, **и** в Studio `.env.prod`, затем перезапустить только нужные контейнеры.

См. также: `docs/08_RUNBOOK_PRODUCTION.md`, `docs/AI_CONTEXT.md`, `docs/06_DECISIONS.md`.
