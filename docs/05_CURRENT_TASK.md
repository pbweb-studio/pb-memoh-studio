# Текущая задача

## После фазы 7a (команды сводок из control group через Event Mirror)

**Статус:** в Studio добавлены таблица `studio_control_commands`, парсер `/summary_today|yesterday|period|latest|help`, сервис скана зеркала и обработки pending, Celery `process_control_group_summary_commands`, админ `GET /control-commands` и `POST /control-commands/process-pending`, env `STUDIO_CONTROL_COMMANDS_ENABLED` / `STUDIO_CONTROL_COMMANDS_MAX_BATCH`. Ответы только в активную control group (`sendMessage`); Memoh не менялся; второго бота и polling/webhook Studio нет; LLM/RAG/SLA/проекты/Studio Admin UI не делались.

**Следующий шаг (без расширения scope):** по плану — фаза **7** (полные сценарии сводок из CG, права) **или** **6+** (LLM) только после отдельной постановки.

**Ограничение:** не подключать внешний LLM и RAG без постановки; Memoh не менять без ADR; SLA / проекты / Studio Admin — вне scope до отдельной фазы.
