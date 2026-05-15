# Active context

**Сейчас (2026-05-15 ~22:20 MSK):** Стратегический разворот. После двух часов отладки off-by-one/«Вижу:» выяснилось что проблема **не решается** патчами skill или watchdog — бот склеивает ответы и в новой сессии с 10 строками истории, и без skill вообще. Это поведение самого Memoh-runtime (как он собирает промпт или ассоциирует ответы).

**Принятое решение: чистый Memoh + надстройки только нативными средствами.**

1. Откатить Memoh до коммита `c1afe432` — убрать `studio_event_mirror.go` (единственная наша правка в core).
2. Удалить старую память бота (Qdrant коллекции + `bot_history_messages`).
3. Настраивать бота **только** через: system prompt в UI, skill-файлы в `/data/skills/`, MCP-подключение к Studio в UI, native settings (compaction, memory, ACL, heartbeat).
4. Studio получает Telegram-апдейты своим отдельным webhook — без хука в Memoh.
5. Все бизнес-фичи (роли, отчёты, проекты, KB, SLA, правила) — через Studio MCP. Это уже работает.

**Что осталось на VPS сейчас (до отката):**
- Memoh: коммит `c1afe432` в ядре + `studio_event_mirror.go`, skill `pb-studio-manager` v2.1 в `/data/skills/`.
- Studio: коммит `a579f65a` (`pb-studio/main`), 20 MCP tools, watchdog timer активен.
- Skill сейчас включён обратно (после A/B-теста).

**Ссылки:** https://jar.pb-web.ru/admin/ · https://memo.pb-web.ru

**Следующий шаг (новый чат):**
1. Прочитать `docs/AI_CONTEXT.md` и этот файл.
2. Откатить Memoh к `c1afe432` (удалить `studio_event_mirror.go`, пересобрать образ, задеплоить).
3. Удалить старую память: Qdrant коллекции бота + все `bot_history_messages` бота `fa57906b-5383-404a-9775-c5821e36fbfc`.
4. Настроить бота нативно: system prompt + skill (только поведенческая часть, без «Анти-галлюцинаций») + MCP на Studio.
5. Studio webhook: добавить прямой Telegram webhook в Studio (или временно работать без зеркала через `studio_get_recent_messages`).
6. Зафиксировать решение в `docs/06_DECISIONS.md`.
