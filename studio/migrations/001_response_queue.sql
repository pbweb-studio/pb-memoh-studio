-- Studio response queue (Postgres). SQLite tests use SQLAlchemy create_all.
-- Apply manually or via Alembic in a later phase.

CREATE TABLE IF NOT EXISTS studio_response_turns (
    id UUID PRIMARY KEY,
    telegram_chat_id BIGINT NOT NULL,
    merged_text TEXT NOT NULL DEFAULT '',
    status VARCHAR(40) NOT NULL DEFAULT 'pending',
    sequence_number INTEGER NOT NULL DEFAULT 0,
    debounce_until TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_studio_turns_chat_status_seq
    ON studio_response_turns (telegram_chat_id, status, sequence_number);

CREATE TABLE IF NOT EXISTS studio_inbound_messages (
    id UUID PRIMARY KEY,
    turn_id UUID NOT NULL REFERENCES studio_response_turns(id) ON DELETE CASCADE,
    telegram_chat_id BIGINT NOT NULL,
    telegram_message_id VARCHAR(128),
    dedupe_key VARCHAR(256) NOT NULL,
    sender_id VARCHAR(128),
    body_text TEXT NOT NULL,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_studio_inbound_dedupe_key UNIQUE (dedupe_key)
);

CREATE INDEX IF NOT EXISTS ix_studio_inbound_turn ON studio_inbound_messages (turn_id);
CREATE INDEX IF NOT EXISTS ix_studio_inbound_chat ON studio_inbound_messages (telegram_chat_id);
