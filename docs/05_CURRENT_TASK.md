# Текущая задача

## MVP v1: role-aware ассистент студии (один PR, один деплой)

**Контракт продукта:** `docs/FEATURES_v1.md`.

### Что сделано в коде (готово к деплою)

1. **9 новых MCP-инструментов Studio** (`studio/pb_studio/mcp_tools/extra_handlers.py`):
   - `studio_get_chat_context(telegram_chat_id, from_user_id?)` — роле-aware контекст для Memoh (role, project, active_rules, can_respond_to_user).
   - `studio_smart_chat_report(chat_id_or_name, period?, max_messages?)` — LLM-отчёт «по смыслу» чата за период.
   - `studio_assign_chat_role(telegram_chat_id, role)` — назначить роль (`client_chat | project_chat | internal_chat | service_chat | unknown`).
   - `studio_set_control_group(telegram_chat_id)` — назначить управляющую группу.
   - `studio_get_active_rules(scope?, scope_id?)` — список активных правил.
   - `studio_create_project(name, slug?)` — создать проект с автогенерацией slug.
   - `studio_bind_chat_to_project(telegram_chat_id, project_slug, role_in_project?)` — привязать чат к проекту.
   - `studio_disable_rule(rule_id, reason?)` — отключить правило.
   - `studio_get_recent_messages(chat_id_or_name, limit?)` — сырьё последних сообщений.
   - Регистрация в FastMCP — `studio/pb_studio/mcp_server/asgi.py`.
2. **Skill `pb-studio-manager` v2** (`skills/pb-studio-manager/SKILL.md`) — поведение по 6 ролям чата, UX-правила, каталог 20 tools.
3. **Удалён legacy Studio NL responder:** все `pb_studio/nl/{processor,router,router_deterministic,gate_service,scan,triggers,turn_input,schemas,constants}.py`, 5 `test_nl_*.py`, route `nl-gate`, Celery task, env `STUDIO_NL_*` и `STUDIO_MEMOH_GATE_TOKEN` в `.env*.example`, `docker-compose.prod.yml`, `pb_studio/core/config.py`. Оставлены `pb_studio/nl/executor.py` и `models.py` как утилиты для MCP-хендлеров.
4. **Тесты:** `studio/tests/test_mcp_extra_handlers.py` (22 теста, все зелёные). Прогон по всем `studio/tests/` — **320 passed**, 1 failed только тест окружения `test_smoke_phase3.py::test_settings_load` (требует переменную `REDIS_URL`, не регрессия).

### Следующий шаг — деплой (один раунд)

1. **Pre-flight аудит VPS (read-only, 5–10 мин):** `docker ps`, `/health`, версии образов; никаких изменений до зелёного результата.
2. **Rollout VPS:** `git pull` на VPS → `docker compose -f docker-compose.prod.yml build studio-api studio-worker studio-beat studio-mcp` → `up -d` → `alembic upgrade head` (миграций по схеме нет, но команда безопасна).
3. **Memoh:** подключить обновлённый skill `pb-studio-manager` (тот же путь, новая версия `SKILL.md`); MCP `tools/list` должен показать +9 инструментов.
4. **Пройти §11 в `docs/AI_CONTEXT.md`** (6 сценариев приёмки).
5. Зафиксировать новый Studio-hash в `docs/AI_CONTEXT.md` и `memory-bank/activeContext.md`.

### Что отложено в PR2 (после успешного MVP)

- UX-фичи U1–U8: self-intro в новом чате, auto-suggest роли, утреннее briefing, inline-подтверждения, голосовой ввод, mute by phrase, onboarding wizard, единая навигация по командам.
- См. `docs/FEATURES_v1.md` секция «UX (PR2)».
