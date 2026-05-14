# Active context

**Сейчас:** фаза **7b** в Studio — UX команд сводок в control group и ACL: `/summary_chats`, `/summary_all_today`, `/summary_all_yesterday`, обновлённый help; env `STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS` (пусто = все участники); статус `failed_access_denied` + короткий отказ + аудит; фильтр `command_name` на `GET /control-commands`; обрезка длинных ответов. База 7a: `studio_control_commands`, scan зеркала, `summaries/product.py`, Celery `process_control_group_summary_commands`. Ответы только в активную control group (`sendMessage`); Memoh не менялся; второго бота и polling/webhook Studio нет.

**Ветка:** `pb-studio/main`.

**Memoh:** не менялся в 7a–7b.

**Следующий шаг:** полная **фаза 7** по плану или **6+** только по отдельной постановке.
