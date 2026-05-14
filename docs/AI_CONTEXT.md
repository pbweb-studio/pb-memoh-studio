# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 8b (SLA: рабочие часы и mute)** — расширение `studio_sla_policies` (Alembic `009_studio_sla_working_hours`): timezone IANA, рабочие дни/часы, holidays, `is_muted` / `muted_until` / `mute_reason`; `sla/calendar.py` — `calculate_due_at` при `STUDIO_SLA_WORKING_HOURS_ENABLED` с учётом только рабочих минут и переносом старта; детектор использует календарь; mute блокирует только **новые** инциденты; API `PATCH /sla/policies/{id}`, mute/unmute; env `STUDIO_SLA_DEFAULT_TIMEZONE`, `STUDIO_SLA_WORKING_HOURS_ENABLED`. **Без** Memoh, **без** второго бота и polling/webhook Studio, **без** LLM/RAG. Memoh **не** менялся.

Фазы **8a**, **7b**–**4b** — см. журнал.

## Текущая цель

Оставшаяся **фаза 8** по плану или **6+** / **7** — только по отдельной постановке.

## Что уже работает

- Фазы 0–8b по Studio: см. `docs/04_PROJECT_LOG.md` и `docs/03_IMPLEMENTATION_PLAN.md`.
- **8a–8b:** SLA по зеркалу, календарь due, mute на policy, админ `/sla/*`.
- **Проверка 4b:** зафиксирована в журнале; актуальные тесты Studio: `pytest tests/` (**144** кейса после фазы 8b, Docker).

## Что ещё не готово

- Внешний LLM, RAG, остальное из фазы 8 (антиспам и т.д.), проекты, Studio Admin; прочие сценарии 6+.

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
