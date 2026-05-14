# Текущая задача

## После фазы 10g (KB импорт из Telegram control group)

**Статус:** команды `/kb_import_last [--project <slug>] <title>` и `/kb_import_file <telegram_file_id> <title>` при `STUDIO_KB_TELEGRAM_IMPORT_ENABLED=true`: зеркало Event Mirror → `getFile` + download тем же `TELEGRAM_BOT_TOKEN` → pipeline **10f** (`ingest_new_document_from_upload`); ACL `STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS`; обновлены `/kb_import_help`, `/kb_help`.

**Следующий шаг:** по постановке — **6+** (LLM для сводок), расширение **10+** (Docling pipeline / KB UX), или иной эпик.
