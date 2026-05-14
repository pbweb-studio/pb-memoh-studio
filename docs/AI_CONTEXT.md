# AI_CONTEXT

## Что строим

Один Telegram-ассистент студии на базе Memoh: архив чатов, сводки, управляющая группа, база знаний (RAG), SLA, проекты, правила поведения. Внутри — Memoh, Studio Layer, MCP, Event Mirror, Response Queue; снаружи — один бот.

## Текущая фаза

**Фаза 9b (Studio: project digest из chat summaries)** — таблица `studio_project_digests` (Alembic `012_studio_project_digests`); пакет `pb_studio/project_digests`; агрегация по активным привязанным чатам и готовым/сгенерированным `studio_chat_summaries` без LLM для текста дайджеста; админ-API `/projects/{id}/digests*`, `/project-digests/*` под `STUDIO_ADMIN_TOKEN`; команды `/project_digest_*` из active control group (тот же Event Mirror + `studio_control_commands`, ACL `STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS`); Celery `generate_daily_project_digests`, `deliver_pending_project_digests`. **Без** Memoh, второго бота, polling/webhook Studio, LLM/RAG для дайджеста, Studio Admin UI; не шлём в client/project/internal/service чаты.

Фазы **9a**, **8a–8c**, **7b**–**4b** — см. журнал.

## Текущая цель

**6+** (LLM/продуктовая доставка сводок) или **RAG/база знаний** (фазы 10+) — только по отдельной постановке.

## Что уже работает

- Фазы 0–9b по Studio: см. `docs/04_PROJECT_LOG.md` и `docs/03_IMPLEMENTATION_PLAN.md`.
- **9a:** проекты в БД, привязка чатов, HTTP API, команды `/project_*` из control group.
- **9b:** project digest (шаблонный текст), API и доставка/команды только в control group.
- **8a–8c:** SLA по зеркалу, календарь due, mute на policy, rate-limit и digest уведомлений, админ `/sla/*`.
- **Проверка 4b:** зафиксирована в журнале; актуальные тесты Studio: `pytest tests/` (**179** кейсов после фазы 9b, локально/Docker).

## Что ещё не готово

- Внешний LLM, RAG/pgvector, Studio Admin; прочие сценарии 6+.

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
- **Фазы 8a–8c:** SLA first response по зеркалу; календарь и mute на policy; уведомления SLA только в control group; см. `docs/06_DECISIONS.md` (фазы 8a–8c).
- **Фаза 9a:** проекты и bind чатов только в Studio DB; команды `/project_*` — те же правила доставки и ACL, что `/summary_*`; см. `docs/06_DECISIONS.md`.
- **Фаза 9b:** project digest из summaries, только Studio DB + шаблон; доставка и команды — только control group; см. `docs/06_DECISIONS.md`.

## Следующая задача

- По постановке: **6+** или **RAG/база знаний** из плана.

## Вопросы к GPT

- нет
