-- Read-only: последние 20 NL-взаимодействий (оператор / VPS).
-- Запуск: psql "$DATABASE_URL" -f studio/scripts/diag_last_nl_interactions.sql
SELECT
    id,
    source_update_id,
    source_message_id,
    left(input_text, 500) AS input_text,
    left(normalized_text, 200) AS normalized_text,
    intent,
    mode,
    status,
    left(coalesce(reply_text, ''), 200) AS reply_text_snippet,
    created_at,
    processed_at,
    left(coalesce(last_error, ''), 200) AS last_error
FROM studio_nl_interactions
ORDER BY created_at DESC
LIMIT 20;
