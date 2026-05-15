---
name: pb-studio-manager
description: Маршрутизация запросов студии к Studio через MCP (бизнес-данные в Postgres Studio), без дублирования в Memoh memory как в CRM.
---

# PB Studio Manager

Используй этот skill, когда пользователь в Telegram просит что-то по **студии**: отчёты по сводкам, SLA, проекты, база знаний, правила поведения, заметки в Studio, playbooks, список зеркалируемых чатов.

## Источник правды

- **Бизнес-факты, KB, SLA, проекты, правила** — только через **MCP-инструменты Studio** (`studio_*`). Не утверждай, что «запомнил» или «сохранил», пока не получен **успешный** результат tool.
- **Личные предпочтения и стиль ответа** — Memoh memory / системный промпт бота; не смешивай с `studio_save_memory_item` без явного запроса пользователя на **бизнес-факт**.

## Доступные инструменты (имена)

1. `studio_list_chats` — человеко-читаемый список чатов (зеркало + control group).
2. `studio_get_report` — сводка по периоду (`today` | `yesterday` | `last_7_days` | `this_week`); `include_debug=true` только по явной просьбе (техполя).
3. `studio_list_open_sla` — открытые SLA-инциденты.
4. `studio_list_projects` — активные проекты.
5. `studio_get_project_digest` — дайджест проекта (нужен `project_name_guess`).
6. `studio_search_kb` — поиск по чанкам KB.
7. `studio_get_kb_sources` — список документов KB.
8. `studio_save_behavior_rule` — правило (`scope`: `global` | `project` | `chat`; для project — `project_slug`; для chat — `studio_chat_id` UUID).
9. `studio_save_memory_item` — факт в `studio_memory_items` (`scope_type`: `global` | `project` + `project_slug`).
10. `studio_create_playbook_draft` — черновик playbook.
11. `studio_runtime_status` — флаги Studio без секретов.

## Правила ответа

- Сначала выбери **один** подходящий инструмент; при нехватке параметров — задай **один** уточняющий вопрос.
- Формулируй ответ пользователю **кратко** на русском; не пересказывай сырой JSON.
- Если инструмент вернул сообщение об отключённом флаге (`STUDIO_KB_ENABLED=false` и т.д.) — объясни, что нужно включить на стороне Studio (оператор), не выдумывай данные.

## Установка в Memoh

1. Скопируй каталог skill (этот `SKILL.md` и метаданные) в каталог skills Memoh, например `/data/skills/pb-studio-manager/` согласно документации Memoh (`docs/docs/getting-started/skills.md` в репозитории Memoh).
2. В Memoh Admin → Bot → Skills включи **pb-studio-manager**.
3. В Memoh Admin → MCP добавь подключение к **`studio-mcp`** (внутренний URL Docker, например `http://studio-mcp:8765`, transport **streamable HTTP** / **http** в зависимости от версии Memoh), заголовок `Authorization: Bearer <STUDIO_MCP_AUTH_TOKEN>` (тот же секрет, что в `.env.prod` Studio).

## Runbook

См. `docs/08_RUNBOOK_PRODUCTION.md` (раздел **H. Single-brain + Studio MCP**).
