-- migrate:up
CREATE TYPE sensitivity   AS ENUM ('private', 'shareable');
CREATE TYPE ingest_state  AS ENUM ('pending', 'indexed', 'failed', 'superseded');
CREATE TYPE salience_tier AS ENUM ('active', 'dormant', 'superseded', 'archived');
CREATE TYPE source_kind   AS ENUM ('obsidian');

CREATE TABLE sources (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind                source_kind NOT NULL,
    external_ref        text NOT NULL,              -- vault-relative POSIX path, e.g. 'Projects/NAS.md'
    title               text,
    sensitivity         sensitivity NOT NULL DEFAULT 'private',
    salience            salience_tier NOT NULL DEFAULT 'active',
    current_revision_id uuid,
    created_at          timestamptz NOT NULL DEFAULT now(),
    deleted_at          timestamptz,                -- tombstone
    UNIQUE (kind, external_ref)
);

CREATE TABLE source_revisions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id    uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    content_hash bytea NOT NULL,                    -- sha256 of normalized text (or of the size/mtime marker, §5.1)
    raw_text     text NOT NULL,
    metadata     jsonb NOT NULL DEFAULT '{}',       -- frontmatter, links, size, mtime_ns, frontmatter_error
    state        ingest_state NOT NULL DEFAULT 'pending',
    error        text,                              -- error code only (§5.6), never content
    observed_at  timestamptz NOT NULL DEFAULT now(),
    indexed_at   timestamptz,
    UNIQUE (source_id, content_hash)
);
CREATE INDEX source_revisions_pending_idx ON source_revisions (source_id, observed_at) WHERE state = 'pending';
ALTER TABLE sources ADD CONSTRAINT sources_current_revision_fk
    FOREIGN KEY (current_revision_id) REFERENCES source_revisions(id);

CREATE TABLE chunks (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    revision_id  uuid NOT NULL REFERENCES source_revisions(id) ON DELETE CASCADE,
    ordinal      int  NOT NULL CHECK (ordinal >= 0),
    heading_path text[] NOT NULL DEFAULT '{}',
    content      text NOT NULL,
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
    UNIQUE (revision_id, ordinal)
);
CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);

CREATE TABLE embedding_spaces (
    id         smallint PRIMARY KEY,
    model      text NOT NULL UNIQUE,
    dims       int  NOT NULL CHECK (dims > 0),
    is_default boolean NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX embedding_spaces_one_default ON embedding_spaces (is_default) WHERE is_default;
INSERT INTO embedding_spaces (id, model, dims, is_default) VALUES (1, 'bge-m3', 1024, true);

CREATE TABLE chunk_embeddings (
    chunk_id  uuid NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    space_id  smallint NOT NULL REFERENCES embedding_spaces(id),
    embedding halfvec NOT NULL,
    PRIMARY KEY (chunk_id, space_id)
);
CREATE INDEX chunk_emb_s1_hnsw ON chunk_embeddings
    USING hnsw ((embedding::halfvec(1024)) halfvec_cosine_ops) WHERE space_id = 1;

CREATE TABLE ingest_runs (
    id          bigserial PRIMARY KEY,
    trigger     text NOT NULL CHECK (trigger IN ('startup', 'schedule', 'manual', 'cli')),
    started_at  timestamptz NOT NULL,
    finished_at timestamptz,
    outcome     text,                               -- 'ok' | 'guard_tripped' | 'vault_unavailable' | 'disabled' | 'error:<code>'
    counts      jsonb NOT NULL DEFAULT '{}'         -- seen, new, changed, moved, tombstoned, requeued_index, requeued_embed, stalled_reset
);

-- migrate:down
DROP TABLE ingest_runs;
DROP TABLE chunk_embeddings;
DROP TABLE embedding_spaces;
DROP TABLE chunks;
ALTER TABLE sources DROP CONSTRAINT sources_current_revision_fk;
DROP TABLE source_revisions;
DROP TABLE sources;
DROP TYPE source_kind;
DROP TYPE salience_tier;
DROP TYPE ingest_state;
DROP TYPE sensitivity;
