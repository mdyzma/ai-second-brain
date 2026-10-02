-- migrate:up
CREATE TABLE eval_embedding_cache (
  model        text NOT NULL,
  input_sha256 bytea NOT NULL,
  embedding    halfvec NOT NULL,
  PRIMARY KEY (model, input_sha256)
);

-- migrate:down
DROP TABLE eval_embedding_cache;
