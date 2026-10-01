-- migrate:up
ALTER TABLE source_revisions ADD COLUMN tags text[] NOT NULL DEFAULT '{}';
CREATE INDEX source_revisions_tags_gin ON source_revisions USING gin (tags);
CREATE INDEX sources_external_ref_prefix ON sources (external_ref text_pattern_ops)
  WHERE deleted_at IS NULL;

-- headings and the title become full-text searchable (weight A)
ALTER TABLE chunks ADD COLUMN heading_text text NOT NULL DEFAULT '';
UPDATE chunks c SET heading_text = btrim(
  CASE WHEN s.title IS NOT NULL AND (cardinality(c.heading_path) = 0 OR c.heading_path[1] <> s.title)
       THEN s.title || ' ' ELSE '' END || array_to_string(c.heading_path, ' '))
FROM source_revisions r JOIN sources s ON s.id = r.source_id
WHERE r.id = c.revision_id;
DROP INDEX IF EXISTS chunks_tsv_gin;
ALTER TABLE chunks DROP COLUMN tsv;
ALTER TABLE chunks ADD COLUMN tsv tsvector GENERATED ALWAYS AS (
  setweight(to_tsvector('simple', heading_text), 'A') || to_tsvector('simple', content)
) STORED;
CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);

-- begin sb_normalise_tags (mirrors search/tags.py::normalise_tags; tested for parity)
CREATE FUNCTION pg_temp.sb_normalise_tags(value jsonb) RETURNS text[]
LANGUAGE sql IMMUTABLE AS $fn$
  WITH items AS (
    SELECT e.item, e.ord
    FROM jsonb_array_elements(CASE WHEN jsonb_typeof(value) = 'array' THEN value ELSE '[]'::jsonb END)
         WITH ORDINALITY AS a(elem, ord)
    CROSS JOIN LATERAL (SELECT a.elem #>> '{}' AS item, a.ord) e
    WHERE jsonb_typeof(a.elem) = 'string'
    UNION ALL
    SELECT s.item, s.ord
    FROM regexp_split_to_table(
           CASE WHEN jsonb_typeof(value) = 'string' THEN value #>> '{}' ELSE '' END, '[,\s]+'
         ) WITH ORDINALITY AS s(item, ord)
  ),
  cleaned AS (
    SELECT lower(btrim(ltrim(btrim(item, E' \t\n\r'), '#'), E' \t\n\r')) AS tag, ord FROM items
  ),
  firsts AS (
    SELECT tag, min(ord) AS ord FROM cleaned
    WHERE tag <> '' AND char_length(tag) <= 100
    GROUP BY tag ORDER BY min(ord) LIMIT 64
  )
  SELECT coalesce(array_agg(tag ORDER BY ord), '{}') FROM firsts
$fn$;
-- end sb_normalise_tags

UPDATE source_revisions
SET tags = pg_temp.sb_normalise_tags(metadata -> 'frontmatter' -> 'tags')
WHERE state IN ('indexed', 'superseded') AND metadata ? 'frontmatter';

DROP FUNCTION pg_temp.sb_normalise_tags(jsonb);

-- migrate:down
DROP INDEX IF EXISTS chunks_tsv_gin;
ALTER TABLE chunks DROP COLUMN tsv;
ALTER TABLE chunks ADD COLUMN tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED;
CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);
ALTER TABLE chunks DROP COLUMN IF EXISTS heading_text;
DROP INDEX IF EXISTS sources_external_ref_prefix;
DROP INDEX IF EXISTS source_revisions_tags_gin;
ALTER TABLE source_revisions DROP COLUMN IF EXISTS tags;
