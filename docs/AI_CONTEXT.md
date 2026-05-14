# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 8c (SLA: антиспам уведомлений в control group)** — таблица `studio_sla_notification_events`, поля инцидента `next_notification_at` / `suppressed_notification_count` / `last_notification_reason` (Alembic `010_studio_sla_notification_events`); `sla/notifications.py`: первое уведомление сразу, повтор по cooldown и `max(cooldown, followup_minutes)`, лимит `STUDIO_SLA_MAX_NOTIFICATIONS_PER_INCIDENT`, digest за один цикл детектора, обрезка текста; события sent/suppressed/failed; ошибки Telegram не валят детектор; токен не попадает в `payload_json`/`error`/`last_error`. Env `STUDIO_SLA_NOTIFICATION_COOLDOWN_MINUTES`, `STUDIO_SLA_NOTIFICATION_DIGEST_MAX_ITEMS`, `STUDIO_SLA_NOTIFICATION_TEXT_MAX_LEN`. API: `GET /sla/notification-events`, `POST /sla/incidents/{id}/notify`, фильтры на `GET /sla/incidents`. **Без** Memoh, второго бота, polling/webhook Studio, LLM/RAG/проектов/Studio Admin UI.

Фазы **8a–8b**, **7b**–**4b** — см. журнал.

## Текущая цель

**6+** или **9** — только по отдельной постановке.

## Что уже работает

- Фазы 0–8c по Studio: см. `docs/04_PROJECT_LOG.md` и `docs/03_IMPLEMENTATION_PLAN.md`.
- **8a–8c:** SLA по зеркалу, календарь due, mute на policy, rate-limit и digest уведомлений, админ `/sla/*`.
- **Проверка 4b:** зафиксирована в журнале; актуальные тесты Studio: `pytest tests/` (**156** кейсов после фазы 8c, Docker).

## Что ещё не готово

- Внешний LLM, RAG, проекты, Studio Admin; прочие сценарии 6+.

## Идентификаторы коммитов (история 4b)

- **Реализация Go-hook 4b:** `67bc573d1b5891f6cf9d3613580f59ca92200ec9`
- **Коммит записи проверки 4b в доках:** `1c8f9f6c0ef1ec71e78c3dcc92879c8c3b8c2b42`
- **Актуальный корень ветки:** `git rev-parse HEAD` на `pb-studio/main`.

**Код Event Mirror Studio (фаза 4a, якорь):** `eb0bdcd94699215118cd9aee41b5827453c21b7f`

**ADR (только текст):** `60a319773fc545be147a29625e3121613002bd7f`

## Файлы Memoh (фаза 4b)

См. предыдущую версию контекста: `telegram.go`, `studio_event_mirror.go`, `studio_event_mirror_test.go`.

## Принятые решения

- Один бот; системные Telegram-сообщения **не** в клиентские/проектные чаты; без control group — только БД / ожидание доставки.
- Outbound Studio: только `sendMessage` в control group; аудит и ретраи — см. `docs/06_DECISIONS.md` (фаза 5b).
- Сводки 6a–6d: Studio DB + шаблон + продуктовый API + доставка в control group — см. `docs/06_DECISIONS.md` (фазы 6a–6d).
- Фазы **7a–7b:** команды `/summary_*` только из зеркала control group → ответы только в control group; ACL по `STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS`; см. `docs/06_DECISIONS.md` (фазы 7a, 7b).
- **Фазы 8a–8b:** SLA first response по зеркалу; календарь и mute на policy; уведомления SLA только в control group; см. `docs/06_DECISIONS.md` (фазы 8a, 8b).

## Следующая задача

- По постановке: продолжение **фазы 8** или **6+** / **7** из плана.

## Вопросы к GPT

- нет
