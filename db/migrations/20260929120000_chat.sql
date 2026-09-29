-- migrate:up
CREATE TYPE chat_mode AS ENUM ('private', 'cloud');

CREATE TABLE chat_sessions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    mode        chat_mode NOT NULL,            -- immutable: no code path updates it
    title       text,                          -- first question, first 80 chars; null until the first saved turn
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX chat_sessions_updated_idx ON chat_sessions (updated_at DESC);

CREATE TABLE chat_turns (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   uuid NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    seq          int  NOT NULL CHECK (seq >= 1),
    question     text NOT NULL,
    answer       text NOT NULL,
    sources      jsonb NOT NULL DEFAULT '[]',  -- snapshot of the Source list shown for this turn
    endpoint     text NOT NULL,                -- endpoint label, or 'anthropic'
    model        text NOT NULL,
    degraded     boolean NOT NULL DEFAULT false,
    started_at   timestamptz NOT NULL,
    finished_at  timestamptz NOT NULL,
    UNIQUE (session_id, seq)
);

-- migrate:down
DROP TABLE chat_turns;
DROP TABLE chat_sessions;
DROP TYPE chat_mode;
