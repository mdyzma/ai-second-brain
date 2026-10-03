-- migrate:up
CREATE TYPE entity_type AS ENUM ('project','person','organization','tool','device','topic');
CREATE TYPE graph_status AS ENUM ('proposed','accepted','rejected');

CREATE TABLE entities (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  type          entity_type NOT NULL,
  name          text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
  norm_name     text NOT NULL,
  status        graph_status NOT NULL DEFAULT 'proposed',
  parent_id     uuid REFERENCES entities(id) ON DELETE SET NULL,
  parent_status graph_status,                -- NULL when parent_id is NULL
  attributes    jsonb NOT NULL DEFAULT '{}',
  created_at    timestamptz NOT NULL DEFAULT now(),
  reviewed_at   timestamptz,
  UNIQUE (type, norm_name),
  CHECK (parent_id IS NULL OR parent_id <> id)
);

CREATE TABLE entity_aliases (
  entity_id  uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  type       entity_type NOT NULL,           -- copied from the entity, kept in sync on retype
  alias      text NOT NULL,
  norm_alias text NOT NULL,
  PRIMARY KEY (type, norm_alias)
);

CREATE TABLE entity_embeddings (
  entity_id uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  space_id  smallint NOT NULL REFERENCES embedding_spaces(id),
  embedding halfvec NOT NULL,
  PRIMARY KEY (entity_id, space_id)
);

CREATE TABLE extractions (
  revision_id       uuid NOT NULL REFERENCES source_revisions(id) ON DELETE CASCADE,
  extractor_version text NOT NULL,
  status            text NOT NULL CHECK (status IN ('ok','failed')),
  error             text,
  model             text NOT NULL,
  summary           text,
  output            jsonb,
  attempted_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (revision_id, extractor_version)
);

CREATE TABLE edges (
  id                uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  src_type          text NOT NULL CHECK (src_type IN ('source','entity')),
  src_id            uuid NOT NULL,
  relation          text NOT NULL CHECK (relation IN
                      ('mentions','about','uses','runs_on','works_with','part_of')),
  dst_entity_id     uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  confidence        real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  origin            text NOT NULL,          -- 'user' | 'llm:<model>'
  status            graph_status NOT NULL DEFAULT 'proposed',
  decided_by        text NOT NULL DEFAULT 'auto' CHECK (decided_by IN ('auto','user')),
  evidence_chunk_id uuid,                   -- may dangle after re-index; treated as absent
  revision_id       uuid,                   -- revision that produced the edge (NULL for user edges)
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (src_type, src_id, relation, dst_entity_id)
);
CREATE INDEX edges_dst ON edges (dst_entity_id, status);
CREATE INDEX edges_src ON edges (src_type, src_id);
CREATE INDEX edges_review ON edges (status, created_at) WHERE status = 'proposed';
CREATE INDEX entities_review ON entities (status, created_at) WHERE status = 'proposed';

-- migrate:down
DROP TABLE edges; DROP TABLE extractions; DROP TABLE entity_embeddings;
DROP TABLE entity_aliases; DROP TABLE entities;
DROP TYPE graph_status; DROP TYPE entity_type;
