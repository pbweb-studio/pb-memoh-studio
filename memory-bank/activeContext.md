# Active context

**Сейчас:** фаза **7a** в Studio — команды `/summary_*` из Telegram control group по зеркалу Event Mirror: `studio_control_commands`, `control_commands/parser` + `service`, Celery `process_control_group_summary_commands`, админ `GET /control-commands` и `POST /control-commands/process-pending`, env `STUDIO_CONTROL_COMMANDS_*` в compose (api/worker). Ответы только в активную control group (`sendMessage`); Memoh не менялся; второго бота и polling/webhook Studio нет.

**Ветка:** `pb-studio/main`.

**Memoh:** не менялся в 7a.

**Следующий шаг:** фаза **7** (полные сценарии из плана) или **6+** только по отдельной постановке.
