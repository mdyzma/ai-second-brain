-- migrate:up
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE auth_sessions (
    id            bytea PRIMARY KEY,              -- sha256(token); the raw token exists only in the cookie
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    user_agent    text
);
CREATE INDEX auth_sessions_expires_idx ON auth_sessions (expires_at);

-- migrate:down
DROP TABLE auth_sessions;
DROP EXTENSION IF EXISTS vector;
