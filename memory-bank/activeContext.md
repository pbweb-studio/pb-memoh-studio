# Active context

**Сейчас (2026-05-15 ~21:40 MSK):** MVP v1 PR1 в продакшене на VPS `148.253.209.54`. Studio MCP-сервис отдаёт 20 инструментов (11 базовых + 9 новых MVP v1). Skill `pb-studio-manager` **v2.1** в Memoh (`/opt/memoh/data/skills/pb-studio-manager/SKILL.md`) — добавлен раздел «Анти-галлюцинации и анти-склейка ответов» против шаблона «Вижу: …» и пересказа прошлых сообщений. Тесты Studio: 320 passed (Studio-код в этом фиксе не менялся).

**Свежий инцидент 21:30 MSK (исправлен):** в DM пользователь увидел «опять off-by-one» + паразитный хвост «Вижу: личку с тобой, группу Управление Jarvis, группу PBVOICE» почти в каждом ответе. На самом деле:

- В Memoh-Postgres orphan-ов **нет**, все user/assistant пары парны (timestamps интервал ~2 мс).
- Корень: грязная DM-сессия `cf704360-dfe6-45e4-8999-e22163a34138` — 114 строк за 2 дня без сброса. Модель один раз сгаллюцинировала имена групп после `get_contacts` (где `chat.title` отсутствовал) и зафиксировала шаблон «Вижу: …» в каждый ответ. Дополнительно склеивала прошлый отчёт в начало новых ответов → пользователь видел «реакция на N-1».

**Что сделано:**
1. Soft-delete сессии: `bot_sessions.deleted_at = now()` + DELETE 114 строк `bot_history_messages` (бэкап в `/opt/pb-studio/backups/memoh-dm-reset/`). Следующий DM создаст новую сессию.
2. `skills/pb-studio-manager/SKILL.md` v2.1: явные правила «один вопрос — один ответ», запрет преамбулы «Вижу: …», запрет выдумывать имена групп без источника.
3. `deploy/scripts/memoh-orphan-cleanup.sh` + `deploy/systemd/memoh-orphan-cleanup.{service,timer}` — каждые 60 с удаляют orphan user-row старше 120 с (страховка от вторичного риска `getUpdates timeout`).
4. ADR в `docs/06_DECISIONS.md` секция «Memoh DM history hygiene (orphan watchdog + skill anti-coalescing)».
5. Memoh-core **не трогали** (правило `040-no-core-damage.mdc`); долгосрочный core-патч (auto-cleanup на стороне Memoh при сбое generation, авто-компакция длинных DM) откладывается в PR2 с отдельным ADR.

**Ссылки:** **https://jar.pb-web.ru/admin/** · **https://memo.pb-web.ru**

**Следующий шаг:**
1. Пользователь — короткий чеклист в DM (5 сообщений), подтверждающий, что бот отвечает по сути и больше не пишет «Вижу: …». См. финальный отчёт в чате.
2. После подтверждения — приёмка §11 в `docs/AI_CONTEXT.md` (6 сценариев MVP v1).
3. PR2: UX U1–U8 + ADR/патч Memoh-core против повторного orphan-а + авто-компакция DM.

**Не сделано (PR2):** UX-фичи U1–U8 (self-intro, auto-suggest, briefing, inline confirms, voice, mute by phrase, onboarding wizard, единая навигация) + патч Memoh-core против orphan + авто-компакция длинных DM сессий.
