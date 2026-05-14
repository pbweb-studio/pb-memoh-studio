# Текущая задача

## После фазы 7b (UX команд сводок и ACL в control group)

**Статус:** команды `/summary_chats`, `/summary_all_today`, `/summary_all_yesterday`; обновлён `/summary_help`; список чатов без активной control group с обрезкой; агрегированные сводки по всем чатам с обрезкой ответа; ACL `STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS` (пусто = все); статус `failed_access_denied` + отказ в Telegram + аудит; фильтр `command_name` на `GET /control-commands`; `redact_secrets` для `last_error` при ошибках. Memoh не менялся.

**Следующий шаг:** по плану — полная **фаза 7** (права/сценарии шире) или **6+** только после отдельной постановки.

**Ограничение:** не подключать внешний LLM и RAG без постановки; Memoh не менять без ADR; SLA / проекты / Studio Admin UI — вне scope до отдельной фазы.
