-- migrate_nl_pending_to_ignored.sql
-- Одноразово после отключения NL: пометить зависшие строки ignored (без DELETE).
-- Проверьте статусы в вашей БД перед запуском.

UPDATE studio_nl_interactions
SET
    status = 'ignored',
    last_error = 'ignored_disabled_single_brain_migration',
    processed_at = (NOW() AT TIME ZONE 'utc')
WHERE status IN ('pending', 'pending_confirmation');
