# Phase 2b: Search, Retrieval in Chat, and Capture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the indexed vault useful through three features: hybrid full-text + vector search (API and Search page), real retrieval with Obsidian-linked citations in private chat, and a capture box that writes Markdown notes into the vault's `Inbox/`.

**Architecture:**
- One `search` package owns the hybrid SQL query: FTS and HNSW CTEs, fused with RRF.
- The same query backs `GET /api/search` and the chat `HybridRetriever`.
- A shared `QueryEmbedder` embeds queries with the existing 2a `Embedder`. It has a 1.5 s cap and a 30 s circuit breaker.
- Capture writes a file with exclusive create. The 2a worker's watcher indexes it.
- The web gets a Search page, a global capture dialog, and links on chat sources.

**Tech Stack:**
- Backend: Python 3.12, FastAPI, psycopg 3 (async), pgvector 0.8.6 `halfvec`, procrastinate 3.10, dbmate.
- Web: React 19, TanStack Router and Query, Tailwind v4 tokens, Radix, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-01-phase-2b-search-retrieval-capture-design.md`. Read it with this plan; the spec wins on conflicts.

## Global Constraints

- **Logs** carry only ids, counts, codes, durations and exception type names. They never carry query text, capture text, file names, note paths, snippets or exception messages (spec §9).
- **Errors** use the `{"detail": "<code>"}` format. Every route requires a session, and POST routes also pass `require_same_origin`.
- **Nothing leaves the LAN.** Query embedding uses `settings.embed_url` and `settings.embed_model` only, and never touches a cloud provider.
- **The default embedding space** is id `1`, `bge-m3`, 1024 dims (seeded by the 2a migration).
  - SQL inlines these as literals through `psycopg.sql`, so the partial HNSW index `chunk_emb_s1_hnsw` (`(embedding::halfvec(1024)) … WHERE space_id = 1`) can be used.
  - They are module constants `SPACE_ID = 1` and `SPACE_DIMS = 1024` in `search/query.py`. Switching models is Phase 3.
  - Ruling: this narrows spec §5.3 "dims read from the default space". The cost if wrong is a small change in Phase 3.
- **Headings are searchable.** Ruling: chunk `content` excludes headings and the note title (2a chunker), so full-text search must index them too. Task 2 adds `chunks.heading_text` and rebuilds `chunks.tsv` as `setweight(to_tsvector('simple', heading_text), 'A') || to_tsvector('simple', content)`. The spec's §5.2 FTS-on-`chunks.tsv` still holds, with a broader `tsv`. Without this, a search for a heading like "Kopie zapasowe" finds nothing by text.
- **`heading_path`** from the 2a chunker starts with the note's H1 title (`["NAS", "Dyski"]`). `Hit.heading_path` drops that leading element when it equals the note title, so the UI shows `Dyski`, not `NAS › Dyski`.
- **RRF** uses k = 60. Each list is capped at 50, the vector candidate scan takes 200, and `SET LOCAL hnsw.ef_search = 200` is set inside the query's transaction.
- **Setting ranges:**
  - `SB_CAPTURE_DIR` defaults to `Inbox`;
  - `SB_OBSIDIAN_VAULT` defaults to the basename of the vault path;
  - `SB_CHAT_NUM_CTX` is 2048–131072, default 8192;
  - `SB_RETRIEVAL_MIN_SIMILARITY` is 0–1, default 0.45.
- **Search API limits:** `q` is 1–500 characters after trimming, and NUL gives 422 `invalid_query`. `limit` is 1–50, default 20. Up to 10 `tag` values.
- **Capture:**
  - `text` is 1–20,000 characters after trimming, and NUL gives 422 `invalid_text`.
  - File name: `{YYYY-MM-DD HHmm} {title}.md`. The title is at most 60 characters, and an empty one falls back to `Capture`. Collisions get ` (2)`…` (99)`, then 409 `capture_name_taken`.
  - A write failure gives 503 `vault_unwritable`.
- **Chat evidence:** about 8,000 characters, at most 2 chunks per note, and `SOURCE_LIMIT` (8) sources.
- **Commits:** Conventional Commits, on `main`. Never add a `Co-Authored-By:` line or any AI attribution. Never push; the owner pushes once at the end of the phase.
- **Running tests:**
  - Backend tests need `just backend::test …`, which sets `TEST_DATABASE_URL`. Run commands in the foreground with timeouts.
  - Never kill Docker, and never blanket-kill node or python.
- **Web UI rules:**
  - Copy is calm and plain. Server text is never shown; codes map to copy in `labels.ts`.
  - Colours come from tokens only. Light and dark modes both work.

## Review Focus

1. **Search text with tsquery syntax** (`"unbalanced`, `-`, `or`, `:*`, `!`, `&`, `|`) must not raise. `websearch_to_tsquery` never errors, and the chat OR query is built only from regex-filtered terms. Pinned in Task 3 (`test_search_odd_query_syntax_never_errors`) and Task 1 (`test_chat_terms_strip_tsquery_operators`).
2. **A note with HTML or `<script>` in its text** must show as literal text in search snippets and chat cards. Pinned in Task 3 (`test_headline_escapes_html`) and Task 7 (`renders a script tag in a snippet as text`).
3. **The first line of a capture contains a path** (`../../etc/passwd`, `C:\x`, `Projects/a`). It must stay a plain file name inside `Inbox/`. Pinned in Task 6 (`test_title_cannot_escape_capture_dir`).
4. **Notes with no `tags` frontmatter, or with odd values** (number, map, `"#a, b c"`, duplicates) must give `[]` or clean tags, never a failure at index time. Pinned in Task 1 (the shared `TAG_CASES` table) and Task 2 (parity with the SQL backfill).
5. **Search while a note is mid-reindex, deleted or failed** must not return a pending, superseded or failed revision, or a tombstone. Pinned in Task 3 (`test_only_current_live_revisions_are_searched`).

---

## File structure

**Backend (`backend/src/ai_second_brain/`)**

| File | Responsibility |
|---|---|
| `config.py` (modify) | the four new settings, their validation, and the `capture_dir` / `obsidian_vault_name` properties |
| `search/__init__.py` | the package docstring |
| `search/tags.py` | `normalise_tags` (pure) |
| `search/links.py` | `obsidian_url` (pure) |
| `search/terms.py` | `ChatTerms`, `chat_terms` (pure) |
| `search/query.py` | `Hit`, `SearchResult`, `query()`: the hybrid SQL |
| `search/embedding.py` | `QueryEmbedder` (1.5 s cap, 30 s breaker) |
| `search/evidence.py` | `select_evidence` (pure budget and per-note cap) |
| `search/retriever.py` | `HybridRetriever` |
| `search/facets.py` | `facets()` SQL |
| `vault/capture.py` | `capture_title`, `write_capture` (sync, run in a thread) |
| `knowledge/index.py`, `knowledge/store.py` (modify) | write `tags` in `finish_index` |
| `chat/retrieval.py`, `chat/models.py`, `chat/events.py`, `chat/service.py`, `chat/providers/ollama.py` (modify) | the `Retrieval` result, `Source.obsidian_url`, `receipt.retrieval`, `num_ctx` |
| `interfaces/api/routes/search.py`, `routes/capture.py` | the new routes |
| `interfaces/api/schemas.py`, `interfaces/api/app.py`, `interfaces/cli/main.py` (modify) | the schemas and the wiring |

**Database:** `db/migrations/20261001120000_search.sql`, and `db/schema.sql` regenerated.

**Web (`web/src/`)**

| File | Responsibility |
|---|---|
| `features/search/{types.ts,api.ts,labels.ts,url.ts,SearchScreen.tsx}` with tests | the Search page |
| `routes/_app/search.tsx` (modify) | route wiring |
| `features/capture/{CaptureDialog.tsx,api.ts,labels.ts,draft.ts}` with tests | the capture dialog |
| `design-system/ui/dialog.tsx` | a Radix dialog wrapper |
| `design-system/AppShell.tsx` (modify) | the Capture button and the `c` shortcut |
| `features/chat/components/SourceList.tsx`, `TurnView.tsx` (modify) | links and the "text only" receipt note |

**Tests and scripts:**
- `backend/tests/unit/test_search_pure.py`
- `test_capture_title.py`
- `test_settings_2b.py`
- `backend/tests/integration/test_search_migration.py`
- `test_search_query.py`
- `test_search_api.py`
- `test_retriever.py`
- `test_capture_api.py`
- `test_privacy_2b.py`
- `backend/tests/fakes/ollama.py` (modify: `embed_topics`)
- `web/tests/e2e/search.spec.ts`
- `backend/tests/e2e_reset.py` (modify)
- `backend/scripts/search_bench.py`

---

### Task 1: Settings and pure search helpers

**Files:**
- Modify: `backend/src/ai_second_brain/config.py`
- Create: `backend/src/ai_second_brain/search/__init__.py`, `search/tags.py`, `search/links.py`, `search/terms.py`
- Test: `backend/tests/unit/test_search_pure.py`, `backend/tests/unit/test_settings_2b.py`

**Interfaces:**
- Produces:
  - `normalise_tags(value: object) -> list[str]`
  - `TAG_CASES: list[tuple[object, list[str]]]`, exported from `tests/unit/test_search_pure.py` for Task 2
  - `obsidian_url(vault_name: str, path: str) -> str | None`
  - `ChatTerms(terms: tuple[str, ...], identifiers: tuple[str, ...])` and `chat_terms(question: str) -> ChatTerms`
  - Settings fields `capture_dir_name: str`, `obsidian_vault: str`, `chat_num_ctx: int`, `retrieval_min_similarity: float`
  - Properties `Settings.capture_dir -> Path | None` and `Settings.obsidian_vault_name -> str`

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_search_pure.py`:

```python
import pytest

from ai_second_brain.search.links import obsidian_url
from ai_second_brain.search.tags import normalise_tags
from ai_second_brain.search.terms import chat_terms

TAG_CASES: list[tuple[object, list[str]]] = [
    (None, []),
    (42, []),
    ({"a": 1}, []),
    ("", []),
    ("homelab", ["homelab"]),
    ("#a, b c", ["a", "b", "c"]),
    ("A,a,#A", ["a"]),
    (["Proj", "#proj", "  x  ", 3, None, ""], ["proj", "x"]),
    (["two words"], ["two words"]),
    (["Zażółć"], ["zażółć"]),
    (["x" * 101, "ok"], ["ok"]),
    ([f"t{i}" for i in range(70)], [f"t{i}" for i in range(64)]),
]


@pytest.mark.parametrize(("value", "expected"), TAG_CASES)
def test_normalise_tags(value: object, expected: list[str]) -> None:
    assert normalise_tags(value) == expected


def test_obsidian_url_encodes_vault_and_file() -> None:
    url = obsidian_url("My Vault", "Projects/NAS #1 & co/Zażółć.md")
    assert url == (
        "obsidian://open?vault=My%20Vault"
        "&file=Projects%2FNAS%20%231%20%26%20co%2FZa%C5%BC%C3%B3%C5%82%C4%87.md"
    )
    assert obsidian_url("", "a.md") is None


def test_chat_terms_identifiers_and_words() -> None:
    terms = chat_terms("What's the IP of nas01? Is 192.168.1.10 or ERR_TIMEOUT in v1.2 ok?")
    assert set(terms.identifiers) == {"nas01", "192.168.1.10", "err_timeout", "v1.2"}
    assert "what" in terms.terms and "the" in terms.terms and "of" not in terms.terms
    assert "ok" not in terms.terms  # words need 3+ characters


def test_chat_terms_cap_prefers_identifiers_then_longest() -> None:
    words = " ".join(f"word{'x' * i}" for i in range(20))
    terms = chat_terms(f"{words} host01")
    assert len(terms.terms) == 16
    assert "host01" in terms.terms
    assert "word" not in terms.terms  # shortest words dropped first


def test_chat_terms_strip_tsquery_operators() -> None:
    terms = chat_terms("a & b | !c :* 'quoted' (paren) <-> \"x\"")
    for term in terms.terms:
        assert all(ch.isalnum() or ch in "._-" for ch in term)


def test_chat_terms_empty() -> None:
    assert chat_terms("?? !! a").terms == ()
```

`backend/tests/unit/test_settings_2b.py`:

```python
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ai_second_brain.config import Settings

from ..conftest import TEST_HASH


def make(**values: Any) -> Settings:
    base: dict[str, Any] = {"DATABASE_URL": "postgres://x@127.0.0.1:1/x", "owner_password_hash": TEST_HASH}
    return Settings(_env_file=None, **(base | values))  # pyright: ignore[reportCallIssue]


def test_defaults(tmp_path: Path) -> None:
    settings = make(vault_path=str(tmp_path / "My Vault"))
    assert settings.capture_dir == tmp_path / "My Vault" / "Inbox"
    assert settings.obsidian_vault_name == "My Vault"
    assert settings.chat_num_ctx == 8192
    assert settings.retrieval_min_similarity == 0.45


def test_no_vault_means_no_capture_dir() -> None:
    settings = make()
    assert settings.capture_dir is None and settings.obsidian_vault_name == ""


@pytest.mark.parametrize("bad", ["../outside", "/abs", "C:\\abs", "a/../../b", ".obsidian/inbox", ""])
def test_capture_dir_must_stay_inside_and_not_excluded(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValidationError):
        make(vault_path=str(tmp_path), SB_CAPTURE_DIR=bad)


def test_capture_dir_nested_ok(tmp_path: Path) -> None:
    assert make(vault_path=str(tmp_path), SB_CAPTURE_DIR="00 Inbox/app").capture_dir == (
        tmp_path / "00 Inbox" / "app"
    )


def test_obsidian_vault_override(tmp_path: Path) -> None:
    assert make(vault_path=str(tmp_path), obsidian_vault="Brain").obsidian_vault_name == "Brain"


@pytest.mark.parametrize(("field", "value"), [("chat_num_ctx", 1024), ("chat_num_ctx", 200000),
                                               ("retrieval_min_similarity", 1.5)])
def test_ranges(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make(**{field: value})
```

If `TEST_HASH` is not exported from `tests/conftest.py`, import it from wherever `ingest_harness.py` imports it.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend; uv run pytest tests/unit/test_search_pure.py tests/unit/test_settings_2b.py -q`
Expected: FAIL with `ModuleNotFoundError: ai_second_brain.search`.

- [ ] **Step 3: Implement**

`backend/src/ai_second_brain/search/__init__.py`:

```python
"""Hybrid search over the indexed vault: full-text + vectors fused with RRF."""
```

`search/tags.py`:

```python
"""Frontmatter tags → a clean list. The SQL backfill in the 2b migration mirrors this exactly."""

import re

_SPLIT = re.compile(r"[,\s]+")
_WS = " \t\n\r"
MAX_TAGS, MAX_TAG_CHARS = 64, 100


def normalise_tags(value: object) -> list[str]:
    if isinstance(value, str):
        items = _SPLIT.split(value)
    elif isinstance(value, list):
        items = [item for item in value if isinstance(item, str)]
    else:
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for item in items:
        tag = item.strip(_WS).lstrip("#").strip(_WS).lower()
        if not tag or len(tag) > MAX_TAG_CHARS or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
        if len(tags) == MAX_TAGS:
            break
    return tags
```

`search/links.py`:

```python
"""obsidian://open links. Obsidian must be installed on the device that opens them."""

from urllib.parse import quote


def obsidian_url(vault_name: str, path: str) -> str | None:
    if not vault_name:
        return None
    return f"obsidian://open?vault={quote(vault_name, safe='')}&file={quote(path, safe='')}"
```

`search/terms.py`:

```python
"""Question → OR-able search terms for chat retrieval. Terms never contain tsquery syntax."""

import re
from dataclasses import dataclass

_TOKEN = re.compile(r"\w(?:[\w.\-]*\w)?")
MAX_TERMS = 16


@dataclass(frozen=True)
class ChatTerms:
    terms: tuple[str, ...]
    identifiers: tuple[str, ...]


def _is_identifier(token: str) -> bool:
    return 2 <= len(token) <= 64 and any(ch.isdigit() or ch in "._-" for ch in token)


def chat_terms(question: str) -> ChatTerms:
    identifiers: list[str] = []
    words: list[str] = []
    for token in _TOKEN.findall(question.lower()):
        bucket = identifiers if _is_identifier(token) else words
        if (_is_identifier(token) or len(token) >= 3) and token not in bucket:
            bucket.append(token)
    words.sort(key=len, reverse=True)
    chosen = (identifiers + words)[:MAX_TERMS]
    return ChatTerms(tuple(chosen), tuple(t for t in identifiers if t in chosen))
```

In `config.py`, add these fields after `max_note_bytes`:

```python
    capture_dir_name: str = Field(default="Inbox", validation_alias="SB_CAPTURE_DIR")
    obsidian_vault: str = ""
    chat_num_ctx: int = Field(default=8192, ge=2048, le=131072)
    retrieval_min_similarity: float = Field(default=0.45, ge=0.0, le=1.0)
```

Add this validator, and the properties below next to `vault_excludes`:

```python
    @model_validator(mode="after")
    def _capture_dir_inside_vault(self) -> "Settings":
        raw = self.capture_dir_name.strip()
        parts = PurePosixPath(raw.replace("\\", "/")).parts
        if (
            not raw
            or PureWindowsPath(raw).is_absolute()
            or raw.startswith(("/", "\\"))
            or ".." in parts
            or ":" in raw
        ):
            raise ValueError("SB_CAPTURE_DIR must be a relative folder inside the vault")
        rel = "/".join(parts)
        if any(fnmatchcase(f"{rel}/x.md", p) or fnmatchcase(f"{rel}/", p) for p in self.vault_excludes):
            raise ValueError("SB_CAPTURE_DIR must not be excluded by SB_VAULT_EXCLUDE")
        self.capture_dir_name = rel
        return self

    @property
    def capture_dir(self) -> Path | None:
        if self.vault_path is None:
            return None
        return self.vault_path.joinpath(*PurePosixPath(self.capture_dir_name).parts)

    @property
    def obsidian_vault_name(self) -> str:
        if self.obsidian_vault.strip():
            return self.obsidian_vault.strip()
        return self.vault_path.name if self.vault_path is not None else ""
```

The imports needed are `from fnmatch import fnmatchcase`, `from pathlib import Path, PurePosixPath, PureWindowsPath`, and `model_validator` from pydantic.

The excluded check mirrors `vault/paths.py::_excluded`. To stay consistent with the `**/` rule, import and reuse `_excluded` from `ai_second_brain.vault.paths` (`_excluded(f"{rel}/x.md", self.vault_excludes)`) instead of the inline `fnmatchcase`, provided that import doesn't create a cycle. `vault.paths` doesn't import `config`.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd backend; uv run pytest tests/unit/test_search_pure.py tests/unit/test_settings_2b.py -q`, then `cd ..; just backend::check`.
Expected: PASS, and the checks are clean.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ai_second_brain/config.py backend/src/ai_second_brain/search backend/tests/unit/test_search_pure.py backend/tests/unit/test_settings_2b.py
git commit -m "feat(search): add search settings, tags, links and chat terms"
```

---

### Task 2: Tags column, backfill and indexing

**Files:**
- Create: `db/migrations/20261001120000_search.sql`
- Modify: every caller of `store.insert_chunks` (grep; tests included)
- Regenerate: `db/schema.sql` (`just db::migrate` then `just db::schema` — use the recipe the repo uses; check `db/justfile`)
- Modify: `backend/src/ai_second_brain/knowledge/store.py` (`finish_index` signature), `backend/src/ai_second_brain/knowledge/index.py`
- Test: `backend/tests/integration/test_search_migration.py`

**Interfaces:**
- Consumes: `normalise_tags` and `TAG_CASES` (Task 1).
- Produces:
  - the column `source_revisions.tags text[]`;
  - the column `chunks.heading_text text`, with `chunks.tsv` rebuilt to include it (weight A);
  - `store.finish_index(conn, source_id, revision_id, title, metadata, tags: list[str])`;
  - `store.insert_chunks(conn, revision_id, chunks, title: str)` and `heading_text(title, heading_path) -> str` (in `store.py`).

- [ ] **Step 1: Write the migration**

`db/migrations/20261001120000_search.sql`:

```sql
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
```

Python's `len()` and SQL's `char_length` both count code points. Python's `lower()` and Postgres's `lower()` agree for the Polish letters in `TAG_CASES`. If the parity test finds a mismatch on a case that is reasonable to support, align the Python to the SQL and record the change in the report.

- [ ] **Step 2: Write the failing tests**

`backend/tests/integration/test_search_migration.py`:

```python
import json
import re
from pathlib import Path

import psycopg
import pytest

from ai_second_brain.search.tags import normalise_tags

from ..conftest import run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import ingest_harness
from ..unit.test_search_pure import TAG_CASES
from ..vaults import VaultBuilder
from ai_second_brain.vault.reconcile import reconcile

pytestmark = pytest.mark.integration
MIGRATION = Path(__file__).parents[3] / "db" / "migrations" / "20261001120000_search.sql"


def sql_function() -> str:
    text = MIGRATION.read_text(encoding="utf-8")
    match = re.search(r"-- begin sb_normalise_tags.*?\n(.*?)-- end sb_normalise_tags", text, re.S)
    assert match
    return match.group(1)


@pytest.mark.parametrize(("value", "expected"), TAG_CASES)
def test_sql_backfill_matches_python(db_url: str, value: object, expected: list[str]) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(sql_function())  # pg_temp: per connection
        row = conn.execute(
            "SELECT pg_temp.sb_normalise_tags(%s::jsonb)", (json.dumps(value),)
        ).fetchone()
    assert row is not None
    assert row[0] == expected == normalise_tags(value)


def test_index_writes_tags(db_url: str, tmp_path: Path, make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    fake: FakeOllama = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "---\ntags: [Homelab, '#nas']\n---\n# A\nx")

    async def scenario() -> None:
        async with ingest_harness(db_url, tmp_path, fake.url) as h:
            await reconcile(h.ctx, trigger="startup")
            await h.drain()
            [row] = await h.rows(
                "SELECT r.tags FROM sources s JOIN source_revisions r ON r.id = s.current_revision_id"
            )
            assert row["tags"] == ["homelab", "nas"]

    run_async(scenario())


def test_headings_and_title_are_full_text_searchable(db_url: str, tmp_path: Path, make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    fake: FakeOllama = make_fake_ollama()
    VaultBuilder(tmp_path).write("NAS.md", "# NAS
## Kopie zapasowe
Co noc o 02:00.")
    VaultBuilder(tmp_path).write("No heading.md", "just body text")

    async def scenario() -> None:
        async with ingest_harness(db_url, tmp_path, fake.url) as h:
            await reconcile(h.ctx, trigger="startup")
            await h.drain()
            rows = await h.rows(
                "SELECT c.heading_text FROM chunks c ORDER BY c.heading_text"
            )
            assert [r["heading_text"] for r in rows] == ["NAS Kopie zapasowe", "No heading"]
            [hit] = await h.rows(
                "SELECT count(*) AS n FROM chunks WHERE tsv @@ websearch_to_tsquery('simple', 'zapasowe')"
            )
            assert hit["n"] == 1

    run_async(scenario())
```

Check how other integration tests type `make_fake_ollama` (for example `Callable[[], FakeOllama]`) and copy that.

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `just backend::test tests/integration/test_search_migration.py -q`
Expected: the parity tests fail until the migration is applied to the test database. The repo's test DB setup (`just test-prepare` or similar; check the justfile) migrates it. `test_index_writes_tags` fails with a missing-column error or `[]`.

- [ ] **Step 4: Apply the migration and implement**

Run the repo's migrate recipes for the dev and test databases, and regenerate `db/schema.sql`. Look in `db/justfile` and the root `justfile` for `migrate`, `test-prepare` and `schema`.

In `store.py`, change `finish_index` so it writes the tags:

```python
async def finish_index(
    conn: AsyncConnection,
    source_id: UUID,
    revision_id: UUID,
    title: str,
    metadata: dict[str, Any],
    tags: list[str],
) -> None:
    await conn.execute(
        "UPDATE source_revisions SET state = 'indexed', indexed_at = now(), error = NULL,"
        " tags = %s, metadata = (metadata - 'embed_error') || %s WHERE id = %s",
        (tags, Jsonb(metadata), revision_id),
    )
    await conn.execute(
        "UPDATE sources SET current_revision_id = %s, title = %s WHERE id = %s",
        (revision_id, title, source_id),
    )
```

Also in `store.py`, write `heading_text` with each chunk:

```python
def heading_text(title: str, heading_path: Sequence[str]) -> str:
    parts = list(heading_path)
    if title and (not parts or parts[0] != title):
        parts.insert(0, title)
    return " ".join(parts)


async def insert_chunks(
    conn: AsyncConnection, revision_id: UUID, chunks: Sequence[Chunk], title: str
) -> None:
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM chunks WHERE revision_id = %s", (revision_id,))
        if chunks:
            await cur.executemany(
                "INSERT INTO chunks (revision_id, ordinal, heading_path, heading_text, content)"
                " VALUES (%s, %s, %s, %s, %s)",
                [
                    (revision_id, c.ordinal, list(c.heading_path),
                     heading_text(title, c.heading_path), c.content)
                    for c in chunks
                ],
            )
```

In `index.py`, call `store.insert_chunks(conn, claimed.revision_id, chunks, parsed.title)`, and pass the tags:

```python
from ai_second_brain.search.tags import normalise_tags
...
        tags = normalise_tags((parsed.frontmatter or {}).get("tags"))
        await store.finish_index(conn, source_id, claimed.revision_id, parsed.title, metadata, tags)
```

Update every other caller of `finish_index` the grep finds (tests included).

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `just backend::test tests/integration/test_search_migration.py -q`, then `just db::schema-check` (or the repo's equivalent), then `just backend::test`.
Expected: everything passes.

- [ ] **Step 6: Commit**

```bash
git add db/migrations/20261001120000_search.sql db/schema.sql backend/src/ai_second_brain/knowledge backend/tests
git commit -m "feat(search): index tags and headings for search"
```

---

### Task 3: The hybrid query

**Files:**
- Create: `backend/src/ai_second_brain/search/query.py`
- Modify: `backend/tests/fakes/ollama.py` (add `embed_topics`)
- Test: `backend/tests/integration/test_search_query.py`

**Interfaces:**
- Consumes: the `tags` column (Task 2), `ChatTerms` (Task 1), and the ingest harness / `reconcile` / `drain` (2a).
- Produces:

```python
SPACE_ID = 1
SPACE_DIMS = 1024
Mode = Literal["search", "chat"]

@dataclass(frozen=True)
class Hit:
    source_id: UUID; path: str; title: str | None
    chunk_id: UUID; heading_path: list[str]; content: str
    headline: str | None; score: float
    matched: frozenset[str]          # {"text"}, {"vector"} or both
    similarity: float | None

@dataclass(frozen=True)
class SearchResult:
    hits: list[Hit]; vector_used: bool

async def query(conn: AsyncConnection, q: str, *, vector: list[float] | None,
                folder: str | None = None, tags: Sequence[str] = (), limit: int = 20,
                mode: Mode = "search", terms: ChatTerms | None = None) -> SearchResult
```

  `mode="search"` returns one hit per source. `mode="chat"` returns up to 2 hits per source and requires `terms`.
- Fake: `FakeOllama.behaviour.embed_topics: dict[str, str]`. An input containing a key (case-insensitive) is embedded as `fake_vector(topic)`.

- [ ] **Step 1: Extend the fake Ollama**

In `backend/tests/fakes/ollama.py`, add this field to the behaviour dataclass:

```python
    embed_topics: dict[str, str] = field(default_factory=dict)  # substring → shared topic vector
```

In `_embed`, replace the `vectors = [...]` line:

```python
        def vector_for(text: str) -> list[float]:
            lowered = text.lower()
            for needle, topic in b.embed_topics.items():
                if needle.lower() in lowered:
                    return fake_vector(f"topic:{topic}", b.embed_dims)
            return fake_vector(text, b.embed_dims)

        vectors = [vector_for(text) for text in inputs]
```

Import `field` from `dataclasses` if it isn't imported already.

- [ ] **Step 2: Write the failing tests**

`backend/tests/integration/test_search_query.py`:

```python
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from ai_second_brain.search.query import query
from ai_second_brain.search.terms import chat_terms
from ai_second_brain.vault.reconcile import reconcile

from ..conftest import run_async
from ..fakes.ollama import FakeOllama, fake_vector
from ..ingest_harness import Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration
MakeFake = Callable[[], FakeOllama]


def indexed(db_url: str, root: Path, fake: FakeOllama, body: Callable[[Harness], Awaitable[None]]) -> None:
    async def scenario() -> None:
        async with ingest_harness(db_url, root, fake.url) as h:
            await reconcile(h.ctx, trigger="startup")
            await h.drain()
            await body(h)

    run_async(scenario())


def topic(name: str) -> list[float]:
    return fake_vector(f"topic:{name}")


def test_exact_identifier_found_by_text(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("Projects/NAS.md", "# NAS\nHost nas01 has four disks.")
    vault.write("Other.md", "# Other\nUnrelated text.")

    async def body(h: Harness) -> None:
        async with h.pool.connection() as conn:
            result = await query(conn, "nas01", vector=fake_vector("unrelated query"))
        assert result.hits[0].path == "Projects/NAS.md"
        assert "text" in result.hits[0].matched
        assert result.hits[0].headline is not None and "<mark>nas01</mark>" in result.hits[0].headline

    indexed(db_url, tmp_path, fake, body)


def test_paraphrase_found_by_vector_only(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    fake.behaviour.embed_topics = {"kopie zapasowe": "backup"}
    vault = VaultBuilder(tmp_path)
    vault.write("NAS.md", "# NAS\n## Kopie zapasowe\nCo noc o 02:00.")
    vault.write("Cats.md", "# Cats\nMeow.")

    async def body(h: Harness) -> None:
        async with h.pool.connection() as conn:
            result = await query(conn, "when do backups run", vector=topic("backup"))
        assert [hit.path for hit in result.hits][0] == "NAS.md"
        assert result.hits[0].matched == frozenset({"vector"})
        assert result.hits[0].headline is None
        assert result.hits[0].similarity is not None and result.hits[0].similarity > 0.99
        assert result.vector_used

    indexed(db_url, tmp_path, fake, body)


def test_both_lists_rank_first(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    fake.behaviour.embed_topics = {"raid": "disks"}
    vault = VaultBuilder(tmp_path)
    vault.write("Both.md", "# Both\nRAID 5 with four disks.")
    vault.write("TextOnly.md", "# TextOnly\nRAID mentioned once.")  # also 'raid' → same topic
    vault.write("Neither.md", "# Neither\nnothing")

    async def body(h: Harness) -> None:
        async with h.pool.connection() as conn:
            result = await query(conn, "four disks", vector=topic("disks"))
        assert result.hits[0].path == "Both.md"
        assert result.hits[0].matched == frozenset({"text", "vector"})

    indexed(db_url, tmp_path, fake, body)


def test_only_current_live_revisions_are_searched(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("keep.md", "# Keep\nzebra current")
    vault.write("gone.md", "# Gone\nzebra deleted")

    async def body(h: Harness) -> None:
        vault.write("keep.md", "# Keep\nzebra pending edit")  # pending, not yet indexed
        vault.delete("gone.md")
        await reconcile(h.ctx, trigger="schedule")  # observes edit (pending), tombstones gone.md
        async with h.pool.connection() as conn:
            hits = (await query(conn, "zebra", vector=None)).hits
        assert [(hit.path, hit.content) for hit in hits] == [("keep.md", "zebra current")]

    indexed(db_url, tmp_path, fake, body)


def test_folder_and_tag_filters(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("Projects/a.md", "---\ntags: [homelab, nas]\n---\n# A\nzebra")
    vault.write("Projects/b.md", "---\ntags: [homelab]\n---\n# B\nzebra")
    vault.write("100%_done/c.md", "# C\nzebra")
    vault.write("100x_done/d.md", "# D\nzebra")

    async def body(h: Harness) -> None:
        async with h.pool.connection() as conn:
            async def paths(**kw: object) -> list[str]:
                return sorted(hit.path for hit in (await query(conn, "zebra", vector=None, **kw)).hits)  # type: ignore[arg-type]
            assert await paths(folder="Projects") == ["Projects/a.md", "Projects/b.md"]
            assert await paths(tags=["homelab", "nas"]) == ["Projects/a.md"]
            assert await paths(folder="100%_done") == ["100%_done/c.md"]

    indexed(db_url, tmp_path, fake, body)


def test_headline_escapes_html(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("x.md", "# X\nzebra <script>alert(1)</script> & co")

    async def body(h: Harness) -> None:
        async with h.pool.connection() as conn:
            [hit] = (await query(conn, "zebra", vector=None)).hits
        assert hit.headline is not None
        assert "<script>" not in hit.headline and "&lt;script&gt;" in hit.headline
        assert "<mark>zebra</mark>" in hit.headline

    indexed(db_url, tmp_path, fake, body)


@pytest.mark.parametrize("q", ['"unbalanced', "-", "or", "a:*", "!x", "a & b | c", "'", "\\"])
def test_search_odd_query_syntax_never_errors(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake, q: str) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("x.md", "# X\nzebra")

    async def body(h: Harness) -> None:
        async with h.pool.connection() as conn:
            await query(conn, q, vector=None)  # must not raise

    indexed(db_url, tmp_path, fake, body)


def test_chat_mode_match_rule_and_two_per_note(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    long_note = "# Big\n" + "\n\n".join(f"## S{i}\nkopie zapasowe NAS sekcja {i} " + "x " * 700 for i in range(4))
    vault.write("Big.md", long_note)
    vault.write("OneWord.md", "# One\nThe kopie only.")
    vault.write("Ident.md", "# Ident\nhost nas01 here")

    async def body(h: Harness) -> None:
        async with h.pool.connection() as conn:
            terms = chat_terms("Kiedy są kopie zapasowe? Co z nas01?")
            result = await query(conn, "", vector=None, mode="chat", terms=terms, limit=16)
        paths = [hit.path for hit in result.hits]
        assert paths.count("Big.md") == 2          # capped at 2 chunks per note
        assert "Ident.md" in paths                 # one identifier is enough
        assert "OneWord.md" not in paths           # one ordinary word is not

    indexed(db_url, tmp_path, fake, body)
```

`VaultBuilder.write` creates parent folders; check this, and if it doesn't, create them in the test. If the 2a chunker splits `Big.md` differently, adjust its size so it produces at least 3 chunks; the assertion stays the same.

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `just backend::test tests/integration/test_search_query.py -q`
Expected: FAIL with `ModuleNotFoundError: ai_second_brain.search.query`.

- [ ] **Step 4: Implement `search/query.py`**

```python
"""One hybrid query: FTS ∪ HNSW, fused with reciprocal rank fusion (k = 60)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from ai_second_brain.search.terms import ChatTerms

SPACE_ID = 1
SPACE_DIMS = 1024
RRF_K = 60
LIST_LIMIT = 50
VECTOR_CANDIDATES = 200
Mode = Literal["search", "chat"]
HEADLINE_OPTS = (
    "StartSel=<mark>, StopSel=</mark>, MaxFragments=2, MaxWords=30, MinWords=12,"
    " FragmentDelimiter=\" … \""
)


@dataclass(frozen=True)
class Hit:
    source_id: UUID
    path: str
    title: str | None
    chunk_id: UUID
    heading_path: list[str]
    content: str
    headline: str | None
    score: float
    matched: frozenset[str]
    similarity: float | None


@dataclass(frozen=True)
class SearchResult:
    hits: list[Hit]
    vector_used: bool


def like_prefix(folder: str) -> str:
    escaped = folder.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}/%"


def _tsquery_sql(mode: Mode) -> sql.Composable:
    if mode == "search":
        return sql.SQL("websearch_to_tsquery('simple', %(q)s)")
    return sql.SQL("to_tsquery('simple', %(or_query)s)")


_STATEMENT = """
WITH live AS (
  SELECT s.id AS source_id, s.external_ref AS path, s.title, s.current_revision_id AS revision_id
  FROM sources s JOIN source_revisions r ON r.id = s.current_revision_id
  WHERE s.deleted_at IS NULL
    AND (%(folder)s::text IS NULL OR s.external_ref LIKE %(folder)s ESCAPE '\\')
    AND r.tags @> %(tags)s::text[]
),
tsq AS (SELECT {tsquery} AS q WHERE %(has_text)s),
fts AS (
  SELECT c.id AS chunk_id,
         row_number() OVER (ORDER BY ts_rank_cd(c.tsv, tsq.q) DESC, c.id) AS rank
  FROM tsq, chunks c JOIN live l ON l.revision_id = c.revision_id
  WHERE c.tsv @@ tsq.q {chat_rule}
  ORDER BY rank LIMIT {list_limit}
),
candidates AS MATERIALIZED (
  SELECT e.chunk_id, e.embedding::halfvec({dims}) <=> %(vec)s::halfvec({dims}) AS distance
  FROM chunk_embeddings e
  WHERE e.space_id = {space} AND %(vec)s::halfvec IS NOT NULL
  ORDER BY e.embedding::halfvec({dims}) <=> %(vec)s::halfvec({dims})
  LIMIT {candidates}
),
vec AS (
  SELECT k.chunk_id, row_number() OVER (ORDER BY k.distance, k.chunk_id) AS rank,
         1 - k.distance AS similarity
  FROM candidates k JOIN chunks c ON c.id = k.chunk_id JOIN live l ON l.revision_id = c.revision_id
  ORDER BY rank LIMIT {list_limit}
),
fused AS (
  SELECT chunk_id, sum(1.0 / ({k} + rank)) AS score,
         bool_or(src = 'text') AS by_text, bool_or(src = 'vector') AS by_vector,
         max(similarity) AS similarity
  FROM (SELECT chunk_id, rank, 'text' AS src, NULL::float8 AS similarity FROM fts
        UNION ALL SELECT chunk_id, rank, 'vector', similarity FROM vec) u
  GROUP BY chunk_id
),
ranked AS (
  SELECT f.*, c.heading_path, c.content, l.source_id, l.path, l.title,
         row_number() OVER (PARTITION BY l.source_id ORDER BY f.score DESC, c.id) AS per_source
  FROM fused f JOIN chunks c ON c.id = f.chunk_id JOIN live l ON l.revision_id = c.revision_id
)
SELECT r.source_id, r.path, r.title, r.chunk_id, r.heading_path, r.content, r.score::float8 AS score,
       r.by_text, r.by_vector, r.similarity,
       CASE WHEN r.by_text THEN ts_headline(
         'simple',
         replace(replace(replace(r.content, '&', '&amp;'), '<', '&lt;'), '>', '&gt;'),
         (SELECT q FROM tsq), {headline_opts}
       ) END AS headline
FROM ranked r
WHERE r.per_source <= %(per_source)s
ORDER BY r.score DESC, r.path, r.per_source
LIMIT %(limit)s
"""

_CHAT_RULE = """
    AND (
      (SELECT count(*) FROM unnest(%(terms)s::text[]) t
        WHERE c.tsv @@ to_tsquery('simple', quote_literal(t))) >= 2
      OR EXISTS (SELECT 1 FROM unnest(%(identifiers)s::text[]) t
        WHERE c.tsv @@ to_tsquery('simple', quote_literal(t)))
    )
"""


def _or_query(terms: ChatTerms) -> str:
    return " | ".join(f"'{term}'" for term in terms.terms)  # terms are [\w.-] only (terms.py)


async def query(
    conn: AsyncConnection[Any],
    q: str,
    *,
    vector: list[float] | None,
    folder: str | None = None,
    tags: Sequence[str] = (),
    limit: int = 20,
    mode: Mode = "search",
    terms: ChatTerms | None = None,
) -> SearchResult:
    if mode == "chat" and terms is None:
        raise ValueError("chat mode needs terms")
    has_text = bool(q.strip()) if mode == "search" else bool(terms and terms.terms)
    statement = sql.SQL(_STATEMENT).format(
        tsquery=_tsquery_sql(mode),
        chat_rule=sql.SQL(_CHAT_RULE if mode == "chat" else ""),
        list_limit=sql.Literal(LIST_LIMIT),
        candidates=sql.Literal(VECTOR_CANDIDATES),
        dims=sql.Literal(SPACE_DIMS),
        space=sql.Literal(SPACE_ID),
        k=sql.Literal(RRF_K),
        headline_opts=sql.Literal(HEADLINE_OPTS),
    )
    params = {
        "q": q,
        "or_query": _or_query(terms) if terms and terms.terms else "",
        "terms": list(terms.terms) if terms else [],
        "identifiers": list(terms.identifiers) if terms else [],
        "has_text": has_text,
        "folder": like_prefix(folder) if folder else None,
        "tags": list(tags),
        "vec": _vector_literal(vector),
        "per_source": 2 if mode == "chat" else 1,
        "limit": limit,
    }
    async with conn.transaction():
        await conn.execute(f"SET LOCAL hnsw.ef_search = {VECTOR_CANDIDATES}")
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(statement, params)
            rows = await cur.fetchall()
    hits = [
        Hit(
            source_id=row["source_id"], path=row["path"], title=row["title"],
            chunk_id=row["chunk_id"], heading_path=_trail(row["title"], row["heading_path"]),
            content=row["content"], headline=_safe_headline(row["headline"]),
            score=row["score"],
            matched=frozenset(n for n, on in (("text", row["by_text"]), ("vector", row["by_vector"])) if on),
            similarity=row["similarity"],
        )
        for row in rows
    ]
    return SearchResult(hits, vector is not None)


def _trail(title: str | None, heading_path: Sequence[str]) -> list[str]:
    parts = list(heading_path)
    return parts[1:] if parts and title is not None and parts[0] == title else parts


def _vector_literal(vector: list[float] | None) -> str | None:
    return None if vector is None else "[" + ",".join(repr(float(v)) for v in vector) + "]"


def _safe_headline(headline: str | None) -> str | None:
    if headline is None:
        return None
    stripped = headline.replace("<mark>", "").replace("</mark>", "")
    return headline if "<" not in stripped and ">" not in stripped else None
```

Notes for the implementer:
- `SET LOCAL` needs the transaction, which is why the `async with conn.transaction()` is there. Pool connections in this repo are autocommit-off by default; check `db.create_pool`. If the connection is already in a transaction, `conn.transaction()` makes a savepoint, which is fine.
- If `ts_rank_cd(c.tsv, tsq.q)` in the window function trips the "WITH tsq where false" case (`has_text` false makes `tsq` empty), the `FROM tsq, chunks` cross join simply yields no rows. That is intended.
- If pgvector rejects the `NULL::halfvec` comparison, compute `candidates` only when `vec` is not None: build two statements, and drop the vector CTE in favour of an empty `vec AS (SELECT NULL::uuid AS chunk_id, 0::bigint AS rank, NULL::float8 AS similarity WHERE false)`. Keep the tests unchanged.
- Confirm with `EXPLAIN` (in a scratch test or psql) that `candidates` uses `chunk_emb_s1_hnsw`. Record the plan line in the report.
- `_safe_headline` returning `None` makes the API fall back to the escaped plain excerpt (Task 4).

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `just backend::test tests/integration/test_search_query.py -q`. Run it twice for stability, then `just backend::check`.
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ai_second_brain/search/query.py backend/tests/fakes/ollama.py backend/tests/integration/test_search_query.py
git commit -m "feat(search): add the hybrid full-text and vector query"
```

---

### Task 4: Query embedding, facets, and the search API

**Files:**
- Create: `backend/src/ai_second_brain/search/embedding.py`, `search/facets.py`, `interfaces/api/routes/search.py`
- Modify: `interfaces/api/schemas.py`, `interfaces/api/app.py`, `backend/tests/unit/test_cli.py` (the operation-id list, if it enumerates them)
- Regenerate: `web/src/api/*` (`just api-client`)
- Test: `backend/tests/unit/test_query_embedder.py`, `backend/tests/integration/test_search_api.py`

**Interfaces:**
- Consumes: `query`, `like_prefix` (Task 3), `normalise_tags` and `obsidian_url` (Task 1), and the 2a `Embedder`.
- Produces:
  - `QueryEmbedder(embedder: Embedder | None, *, timeout: float = 1.5, cooldown: float = 30.0, clock: Callable[[], float] = time.monotonic)` with `async embed(text) -> list[float] | None`. It is stored at `app.state.query_embedder`.
  - `excerpt(content: str, limit: int = 240) -> str`, which returns HTML-escaped text cut at a word boundary.
  - `facets(conn) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]`.
  - Operation ids `searchNotes` and `searchFacets`; schemas `SearchResponse`, `SearchHit` and `SearchFacets`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_query_embedder.py`:

```python
import asyncio

from ai_second_brain.knowledge.embedder import EmbedError
from ai_second_brain.runtime import new_event_loop
from ai_second_brain.search.embedding import QueryEmbedder, excerpt


class FakeEmbedder:
    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        self.fail, self.delay, self.calls = fail, delay, 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.fail:
            raise EmbedError("embed_unreachable")
        return [[0.1] * 3]


def run(coro):  # type: ignore[no-untyped-def]
    loop = new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_returns_vector() -> None:
    assert run(QueryEmbedder(FakeEmbedder()).embed("q")) == [0.1] * 3  # type: ignore[arg-type]


def test_none_without_embedder() -> None:
    assert run(QueryEmbedder(None).embed("q")) is None


def test_breaker_skips_calls_for_cooldown() -> None:
    now = [100.0]
    fake = FakeEmbedder(fail=True)
    embedder = QueryEmbedder(fake, cooldown=30, clock=lambda: now[0])  # type: ignore[arg-type]
    assert run(embedder.embed("q")) is None and fake.calls == 1
    now[0] = 120.0
    assert run(embedder.embed("q")) is None and fake.calls == 1
    now[0] = 131.0
    fake.fail = False
    assert run(embedder.embed("q")) == [0.1] * 3 and fake.calls == 2


def test_timeout_counts_as_failure() -> None:
    fake = FakeEmbedder(delay=0.5)
    assert run(QueryEmbedder(fake, timeout=0.05).embed("q")) is None  # type: ignore[arg-type]


def test_excerpt_escapes_and_cuts_at_word() -> None:
    text = "<b>bold</b> & " + "word " * 100
    out = excerpt(text, 40)
    assert out.startswith("&lt;b&gt;bold&lt;/b&gt; &amp;") and len(out) <= 41 and out.endswith("…")
```

`backend/tests/integration/test_search_api.py`. It uses the `make_api` / `seed` pattern from `test_sources_api.py`; copy the `db` and `make_api` fixtures and the `seed` helper.

```python
def test_search_returns_hits_with_links_and_vector_status(make_api, db_url, tmp_path, make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path / "Brain")
    vault.write("Projects/NAS.md", "---\ntags: [homelab]\n---\n# NAS\n## Dyski\nCztery dyski.")
    seed(db_url, tmp_path / "Brain", fake.url)
    client = make_api(vault_path=str(tmp_path / "Brain"), embed_url_override=fake.url)
    body = client.get("/api/search", params={"q": "dyski"}).json()
    assert body["vector"] == "ok"
    [hit] = body["results"]
    assert hit["path"] == "Projects/NAS.md" and hit["title"] == "NAS"
    assert hit["heading_path"] == ["Dyski"]
    assert "<mark>dyski</mark>" in hit["snippet"].lower()
    assert "text" in hit["matched"]
    assert hit["obsidian_url"] == "obsidian://open?vault=Brain&file=Projects%2FNAS.md"


def test_search_falls_back_to_text_when_ollama_down(make_api, db_url, tmp_path, make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "# A\nzebra")
    seed(db_url, tmp_path, fake.url)
    fake.behaviour.embed_status = 500
    client = make_api(vault_path=str(tmp_path), embed_url_override=fake.url)
    body = client.get("/api/search", params={"q": "zebra"}).json()
    assert body["vector"] == "unavailable" and [r["path"] for r in body["results"]] == ["a.md"]
    calls = len(fake.embed_requests())
    client.get("/api/search", params={"q": "zebra"})
    assert len(fake.embed_requests()) == calls  # breaker: no second attempt within 30 s


def test_search_filters_and_validation(make_api, db_url, tmp_path, make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("Projects/a.md", "---\ntags: [homelab]\n---\n# A\nzebra")
    vault.write("Journal/b.md", "# B\nzebra")
    seed(db_url, tmp_path, fake.url)
    client = make_api(vault_path=str(tmp_path), embed_url_override=fake.url)
    paths = lambda **p: [r["path"] for r in client.get("/api/search", params={"q": "zebra", **p}).json()["results"]]  # noqa: E731
    assert paths(folder="Projects") == ["Projects/a.md"]
    assert paths(tag=["#HomeLab"]) == ["Projects/a.md"]
    assert client.get("/api/search", params={"q": "  "}).status_code == 422
    assert client.get("/api/search", params={"q": "a\x00b"}).json() == {"detail": "invalid_query"}
    assert client.get("/api/search", params={"q": "x" * 501}).status_code == 422
    assert client.get("/api/search", params={"q": "x", "limit": 51}).status_code == 422


def test_search_needs_vault_and_session(make_api, db_url) -> None:  # type: ignore[no-untyped-def]
    client = make_api()
    assert client.get("/api/search", params={"q": "x"}).json() == {"detail": "vault_disabled"}
    anon = make_api(login=False)
    assert anon.get("/api/search", params={"q": "x"}).status_code == 401


def test_facets(make_api, db_url, tmp_path, make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("Projects/Home/a.md", "---\ntags: [homelab, nas]\n---\nx")
    vault.write("Projects/b.md", "---\ntags: [homelab]\n---\nx")
    vault.write("root.md", "x")
    seed(db_url, tmp_path, fake.url)
    client = make_api(vault_path=str(tmp_path), embed_url_override=fake.url)
    body = client.get("/api/search/facets").json()
    assert body["folders"] == [{"path": "Projects", "count": 2}, {"path": "Projects/Home", "count": 1}]
    assert body["tags"] == [{"tag": "homelab", "count": 2}, {"tag": "nas", "count": 1}]
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend; uv run pytest tests/unit/test_query_embedder.py -q`, then `cd ..; just backend::test tests/integration/test_search_api.py -q`
Expected: FAIL with an import error or 404.

- [ ] **Step 3: Implement**

`search/embedding.py`:

```python
"""Embed one query for search or chat: 1.5 s cap, then a 30 s breaker. Logs codes only."""

import asyncio
import html
import logging
import time
from collections.abc import Callable
from typing import Protocol

from ai_second_brain.knowledge.embedder import EmbedError

logger = logging.getLogger("ai_second_brain.search")


class _Embeds(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class QueryEmbedder:
    def __init__(
        self,
        embedder: _Embeds | None,
        *,
        timeout: float = 1.5,
        cooldown: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._embedder, self._timeout, self._cooldown, self._clock = embedder, timeout, cooldown, clock
        self._down_until = 0.0

    async def embed(self, text: str) -> list[float] | None:
        if self._embedder is None or self._clock() < self._down_until:
            return None
        try:
            async with asyncio.timeout(self._timeout):
                [vector] = await self._embedder.embed([text])
        except (EmbedError, TimeoutError, ValueError) as error:
            code = error.code if isinstance(error, EmbedError) else "embed_timeout"
            logger.warning("query_embed_unavailable code=%s", code)
            self._down_until = self._clock() + self._cooldown
            return None
        return vector


def excerpt(content: str, limit: int = 240) -> str:
    text = " ".join(content.split())
    if len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0] or text[:limit]
        text = cut + "…"
    return html.escape(text, quote=False)
```

`search/facets.py`:

```python
"""Folder (two levels) and tag counts over live, searchable notes."""

from typing import Any

from psycopg import AsyncConnection

_FOLDERS = """
SELECT folder, count(*) FROM (
  SELECT DISTINCT s.id, f.folder
  FROM sources s
  CROSS JOIN LATERAL (
    SELECT array_to_string((string_to_array(s.external_ref, '/'))[1:n], '/') AS folder
    FROM generate_series(1, least(2, array_length(string_to_array(s.external_ref, '/'), 1) - 1)) n
  ) f
  WHERE s.deleted_at IS NULL AND s.current_revision_id IS NOT NULL
) x GROUP BY folder ORDER BY folder
"""
_TAGS = """
SELECT t, count(*) FROM sources s
JOIN source_revisions r ON r.id = s.current_revision_id
CROSS JOIN LATERAL unnest(r.tags) t
WHERE s.deleted_at IS NULL
GROUP BY t ORDER BY count(*) DESC, t LIMIT 200
"""


async def facets(conn: AsyncConnection[Any]) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    folders = await (await conn.execute(_FOLDERS)).fetchall()
    tags = await (await conn.execute(_TAGS)).fetchall()
    return [(f, n) for f, n in folders], [(t, n) for t, n in tags]
```

In `schemas.py`, add the following (match the module's existing `BaseModel` style):

```python
class SearchHit(BaseModel):
    source_id: UUID
    path: str
    title: str | None
    heading_path: list[str]
    snippet: str
    matched: list[Literal["text", "vector"]]
    score: float
    obsidian_url: str | None


class SearchResponse(BaseModel):
    vector: Literal["ok", "unavailable"]
    results: list[SearchHit]


class FolderFacet(BaseModel):
    path: str
    count: int


class TagFacet(BaseModel):
    tag: str
    count: int


class SearchFacets(BaseModel):
    folders: list[FolderFacet]
    tags: list[TagFacet]
```

`interfaces/api/routes/search.py`:

```python
import logging
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ai_second_brain.interfaces.api.deps import get_settings, require_session
from ai_second_brain.interfaces.api.schemas import (
    ErrorResponse, FolderFacet, SearchFacets, SearchHit, SearchResponse, TagFacet,
)
from ai_second_brain.search.embedding import excerpt
from ai_second_brain.search.facets import facets
from ai_second_brain.search.links import obsidian_url
from ai_second_brain.search.query import query
from ai_second_brain.search.tags import normalise_tags

logger = logging.getLogger("ai_second_brain.search")
router = APIRouter(tags=["search"], dependencies=[Depends(require_session)])
ERRORS: dict[int | str, dict[str, Any]] = {k: {"model": ErrorResponse} for k in (401, 409, 422, 503)}


def _require_vault(request: Request) -> None:
    if get_settings(request).vault_path is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="vault_disabled")


@router.get("/search", operation_id="searchNotes", response_model=SearchResponse, responses=ERRORS)
async def search_notes(
    request: Request,
    q: Annotated[str, Query(max_length=500)],
    folder: Annotated[str | None, Query(max_length=500)] = None,
    tag: Annotated[list[str], Query(max_length=10)] = [],  # noqa: B006 - FastAPI query default
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchResponse:
    _require_vault(request)
    text = q.strip()
    if not text or "\x00" in q or (folder and "\x00" in folder):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_query")
    settings = get_settings(request)
    started = time.perf_counter()
    vector = await request.app.state.query_embedder.embed(text)
    tags = normalise_tags(tag)
    async with request.app.state.pool.connection() as conn:
        result = await query(conn, text, vector=vector, folder=(folder or "").strip("/") or None,
                             tags=tags, limit=limit)
    vault_name = settings.obsidian_vault_name
    hits = [
        SearchHit(
            source_id=hit.source_id, path=hit.path, title=hit.title, heading_path=hit.heading_path,
            snippet=hit.headline or excerpt(hit.content), matched=sorted(hit.matched),  # type: ignore[arg-type]
            score=hit.score, obsidian_url=obsidian_url(vault_name, hit.path),
        )
        for hit in result.hits
    ]
    logger.info(
        "search q_len=%d filters=%d results=%d vector=%s ms=%d",
        len(text), int(bool(folder)) + len(tags), len(hits),
        "ok" if result.vector_used else "unavailable", (time.perf_counter() - started) * 1000,
    )
    return SearchResponse(vector="ok" if result.vector_used else "unavailable", results=hits)


@router.get("/search/facets", operation_id="searchFacets", response_model=SearchFacets, responses=ERRORS)
async def search_facets(request: Request) -> SearchFacets:
    _require_vault(request)
    async with request.app.state.pool.connection() as conn:
        folders, tags = await facets(conn)
    return SearchFacets(
        folders=[FolderFacet(path=p, count=n) for p, n in folders],
        tags=[TagFacet(tag=t, count=n) for t, n in tags],
    )
```

The app maps `RequestValidationError` to `invalid_request` (422). The test only checks the status for `"  "`, `x*501` and `limit=51`, and checks `invalid_query` for NUL. That is consistent.

In `app.py`'s lifespan, after building `embedder`, add:

```python
        app.state.query_embedder = QueryEmbedder(embedder)
```

Then `app.include_router(search.router, prefix="/api")` and import `search`. If `tests/unit/test_cli.py` lists operation ids, add `searchNotes` and `searchFacets`.

- [ ] **Step 4: Run the tests and confirm they pass, then regenerate the client**

Run: the unit and integration tests above, then `just api-client`, `just backend::test` and `just check`.
Expected: PASS. `web/src/api/*` changes only by the new paths and schemas.

- [ ] **Step 5: Commit**

```bash
git add backend/src backend/tests web/src/api
git commit -m "feat(api): add hybrid search and facet endpoints"
```

---

### Task 5: Retrieval in private chat

**Files:**
- Create: `backend/src/ai_second_brain/search/evidence.py`, `search/retriever.py`
- Modify:
  - `chat/retrieval.py`, `chat/models.py`, `chat/events.py`, `chat/service.py`, `chat/providers/ollama.py`;
  - `interfaces/api/app.py`, `interfaces/cli/main.py`;
  - `backend/tests/fakes/chat.py`, `backend/tests/unit/test_ollama_provider.py`.
- Regenerate: `web/src/api/*`
- Test: `backend/tests/unit/test_evidence.py`, `backend/tests/integration/test_retriever.py`, plus updates to the existing chat tests

**Interfaces:**
- Consumes: `query`, `Hit` (Task 3), `QueryEmbedder` (Task 4), `chat_terms` and `obsidian_url` (Task 1).
- Produces:
  - `chat/retrieval.py`:

    ```python
    RetrievalMode = Literal["hybrid", "text_only", "none"]

    @dataclass(frozen=True)
    class Retrieval:
        sources: list[Source]
        mode: RetrievalMode

    class Retriever(Protocol):
        async def retrieve(self, question: str, limit: int) -> Retrieval: ...
    ```

    `NullRetriever` returns `Retrieval([], "none")`.
  - `Source.obsidian_url: str | None = None`.
  - `ReceiptEvent.retrieval: RetrievalMode = "none"`.
  - `select_evidence(hits: Sequence[Hit], *, limit: int, budget_chars: int = 8000, per_note: int = 2) -> list[Hit]`.
  - `HybridRetriever(pool, query_embedder, settings)`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_evidence.py`:

```python
from uuid import uuid4

from ai_second_brain.search.evidence import select_evidence
from ai_second_brain.search.query import Hit


def hit(source: str, size: int, score: float) -> Hit:
    return Hit(uuid4() if source == "" else _ids.setdefault(source, uuid4()), source, None, uuid4(), [],
               "x" * size, None, score, frozenset({"text"}), None)


_ids: dict[str, object] = {}


def test_budget_skips_oversized_and_keeps_order() -> None:
    hits = [hit("a", 5000, 0.9), hit("b", 4000, 0.8), hit("c", 2000, 0.7), hit("d", 900, 0.6)]
    chosen = select_evidence(hits, limit=8, budget_chars=8000)
    assert [h.path for h in chosen] == ["a", "c", "d"]


def test_per_note_cap_and_limit() -> None:
    hits = [hit("a", 10, 1.0 - i / 100) for i in range(5)] + [hit(f"n{i}", 10, 0.5) for i in range(10)]
    chosen = select_evidence(hits, limit=8)
    assert [h.path for h in chosen].count("a") == 2 and len(chosen) == 8
```

`backend/tests/integration/test_retriever.py` uses the ingest harness, a `QueryEmbedder` built over the harness embedder, and `Settings` from `h.ctx.settings`:

```python
def test_retriever_cutoff_cap_and_links(db_url, tmp_path, make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    fake = make_fake_ollama()
    fake.behaviour.embed_topics = {"backup": "backup", "kopie zapasowe": "backup"}
    vault = VaultBuilder(tmp_path / "Brain")
    vault.write("NAS.md", "# NAS\n## Kopie zapasowe\nCo noc o 02:00.")
    vault.write("Cats.md", "# Cats\nMeow.")

    async def scenario() -> None:
        async with ingest_harness(db_url, tmp_path / "Brain", fake.url) as h:
            await reconcile(h.ctx, trigger="startup")
            await h.drain()
            retriever = HybridRetriever(h.pool, QueryEmbedder(h.ctx.embedder), h.ctx.settings)
            result = await retriever.retrieve("when does the backup run?", 8)
            assert result.mode == "hybrid"
            assert [s.path for s in result.sources] == ["NAS.md"]  # Cats is below the similarity floor
            [source] = result.sources
            assert source.heading == "Kopie zapasowe" and source.snippet.startswith("Co noc")
            assert source.obsidian_url == "obsidian://open?vault=Brain&file=NAS.md"
            fake.behaviour.embed_status = 500
            text_only = await HybridRetriever(h.pool, QueryEmbedder(h.ctx.embedder), h.ctx.settings).retrieve(
                "kopie zapasowe NAS", 8
            )
            assert text_only.mode == "text_only" and [s.path for s in text_only.sources] == ["NAS.md"]

    run_async(scenario())
```

Also extend the existing chat-service tests (find them with `grep -rn "StaticRetriever" backend/tests`):
- the receipt carries `retrieval` (`"hybrid"` from a `StaticRetriever` returning `Retrieval(sources, "hybrid")`);
- cloud mode with `SpyRetriever` still never retrieves, and the receipt has `retrieval == "none"`.

In `test_ollama_provider.py`, update the expected request body to `"options": {"num_predict": 321, "num_ctx": <value passed>}`. The pool/provider now takes `num_ctx`.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend; uv run pytest tests/unit/test_evidence.py -q`, then `cd ..; just backend::test tests/integration/test_retriever.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`search/evidence.py`:

```python
"""Pick chat evidence: score order, ≤2 chunks per note, ≤limit chunks, ≈8,000 characters."""

from collections import Counter
from collections.abc import Sequence

from ai_second_brain.search.query import Hit


def select_evidence(
    hits: Sequence[Hit], *, limit: int, budget_chars: int = 8000, per_note: int = 2
) -> list[Hit]:
    chosen: list[Hit] = []
    per_source: Counter[object] = Counter()
    used = 0
    for hit in hits:
        if len(chosen) == limit:
            break
        if per_source[hit.source_id] >= per_note or used + len(hit.content) > budget_chars:
            continue
        chosen.append(hit)
        per_source[hit.source_id] += 1
        used += len(hit.content)
    return chosen
```

`search/retriever.py`:

```python
"""The real chat Retriever: hybrid query in chat mode, similarity floor, evidence budget."""

import logging
import time
from typing import Any

from psycopg_pool import AsyncConnectionPool

from ai_second_brain.chat.models import Source
from ai_second_brain.chat.retrieval import Retrieval
from ai_second_brain.config import Settings
from ai_second_brain.search.embedding import QueryEmbedder
from ai_second_brain.search.evidence import select_evidence
from ai_second_brain.search.links import obsidian_url
from ai_second_brain.search.query import query
from ai_second_brain.search.terms import chat_terms

logger = logging.getLogger("ai_second_brain.search")


class HybridRetriever:
    def __init__(self, pool: AsyncConnectionPool[Any], embedder: QueryEmbedder, settings: Settings) -> None:
        self._pool, self._embedder, self._settings = pool, embedder, settings

    async def retrieve(self, question: str, limit: int) -> Retrieval:
        started = time.perf_counter()
        vector = await self._embedder.embed(question)
        terms = chat_terms(question)
        async with self._pool.connection() as conn:
            result = await query(conn, question, vector=vector, mode="chat", terms=terms, limit=limit * 2)
        floor = self._settings.retrieval_min_similarity
        relevant = [
            hit for hit in result.hits
            if "text" in hit.matched or (hit.similarity is not None and hit.similarity >= floor)
        ]
        vault = self._settings.obsidian_vault_name
        sources = [
            Source(
                n=i, source_id=str(hit.source_id), path=hit.path,
                heading=" › ".join(hit.heading_path) or None, score=hit.score,
                snippet=hit.content, obsidian_url=obsidian_url(vault, hit.path),
            )
            for i, hit in enumerate(select_evidence(relevant, limit=limit), start=1)
        ]
        mode = "hybrid" if vector is not None else "text_only"
        logger.info("retrieve q_len=%d sources=%d mode=%s ms=%d", len(question), len(sources), mode,
                    (time.perf_counter() - started) * 1000)
        return Retrieval(sources, mode)
```

`chat/retrieval.py`:

```python
"""Retrieval seam: the chat service asks for evidence and learns how it was found."""

from dataclasses import dataclass
from typing import Literal, Protocol

from ai_second_brain.chat.models import Source

RetrievalMode = Literal["hybrid", "text_only", "none"]


@dataclass(frozen=True)
class Retrieval:
    sources: list[Source]
    mode: RetrievalMode


class Retriever(Protocol):
    async def retrieve(self, question: str, limit: int) -> Retrieval: ...


class NullRetriever:
    async def retrieve(self, question: str, limit: int) -> Retrieval:
        return Retrieval([], "none")
```

`chat/models.py`: add `obsidian_url: str | None = None` to `Source`.

`chat/events.py`: add `retrieval: Literal["hybrid", "text_only", "none"] = "none"` to `ReceiptEvent`.

`chat/service.py`:
- `_retrieve` returns a `Retrieval` and renumbers `sources` as it does today.
- In `run_turn`:

  ```python
  retrieval = await self._retrieve(question) if tier is Tier.LOCAL else Retrieval([], "none")
  sources = retrieval.sources
  ```

  Pass `retrieval=retrieval.mode if sources else "none"` to `ReceiptEvent`. Keep the `text_only` mode even when there are zero sources: use `retrieval.mode` when it is `"text_only"`.

`chat/providers/ollama.py`:
- Add a `num_ctx: int` parameter to `OllamaProvider.__init__` and `OllamaPool.__init__` (keyword, required), store it, and send `"options": {"num_predict": self._max_tokens, "num_ctx": self._num_ctx}`.
- Update every `OllamaPool(...)` construction (`app.py`, `cli/main.py`, tests) to pass `num_ctx=settings.chat_num_ctx`. Tests can pass `num_ctx=8192`.

`tests/fakes/chat.py`: `StaticRetriever.retrieve` returns `Retrieval(self.sources, "hybrid" if self.sources else "none")`. `SpyRetriever` and `FailingRetriever` keep their behaviour with the new return type.

In the `app.py` lifespan, build the retriever after the pool and `query_embedder`. Move `app.state.query_embedder` creation above `ChatService` construction, and then:

```python
        chat_retriever = retriever or (
            HybridRetriever(pool, app.state.query_embedder, settings)
            if settings.vault_path is not None else NullRetriever()
        )
```

Pass `chat_retriever` to `ChatService`. The `embedder` must therefore be built before `ChatService`: reorder the lines and keep `http_client` creation first.

`cli/main.py` chat command: when `settings.vault_path` is set, build a `HybridRetriever` with a `QueryEmbedder(Embedder(...))` over its own http client. Otherwise use `NullRetriever`. Mirror how the CLI already builds `OllamaPool`.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd backend; uv run pytest tests/unit -q`, `cd ..; just backend::test`, `just api-client`, `just check`.
Expected: PASS. The web client gains `obsidian_url` and `retrieval`. Fix any web type errors from the regenerated client in the files that construct `Source` fixtures (add `obsidian_url: null`).

- [ ] **Step 5: Commit**

```bash
git add backend web/src/api web/src
git commit -m "feat(chat): retrieve cited notes in private chat"
```

---

### Task 6: Capture API and the privacy test

**Files:**
- Create: `backend/src/ai_second_brain/vault/capture.py`, `interfaces/api/routes/capture.py`
- Modify: `interfaces/api/schemas.py`, `interfaces/api/app.py`, `tests/unit/test_cli.py` (operation ids, if listed)
- Regenerate: `web/src/api/*`
- Test: `backend/tests/unit/test_capture_title.py`, `backend/tests/integration/test_capture_api.py`, `backend/tests/integration/test_privacy_2b.py`

**Interfaces:**
- Produces:
  - `capture_title(text: str) -> str`;
  - `CaptureNameTaken(Exception)`;
  - `write_capture(vault_root: Path, capture_dir: Path, text: str, now: datetime) -> str`, which returns the vault-relative POSIX path. It is sync and runs via `asyncio.to_thread`;
  - operation id `captureNote`, schemas `CaptureRequest` and `CaptureResponse`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_capture_title.py`:

```python
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_second_brain.vault.capture import CaptureNameTaken, capture_title, write_capture

NOW = datetime(2026, 10, 1, 14, 32, 5, tzinfo=timezone(timedelta(hours=2)))


@pytest.mark.parametrize(("text", "title"), [
    ("Check NAS backup schedule\nmore", "Check NAS backup schedule"),
    ("\n\n  # Heading line  \nbody", "Heading line"),
    ('a\\b/c:d*e?f"g<h>i|j#k^l[m]n', "abcdefghijklmn"),
    ("Zażółć gęślą jaźń", "Zażółć gęślą jaźń"),
    ("word " * 30, "word word word word word word word word word word word word"),
    ("...", "Capture"),
    ("   \n  ", "Capture"),
    ("trailing dots...", "trailing dots"),
    ("tab\tand\x07bell", "tab and bell"),
])
def test_capture_title(text: str, title: str) -> None:
    assert capture_title(text) == title


@pytest.mark.parametrize("first", ["../../etc/passwd", "C:\\x\\y", "Projects/a", "/abs"])
def test_title_cannot_escape_capture_dir(tmp_path: Path, first: str) -> None:
    rel = write_capture(tmp_path, tmp_path / "Inbox", f"{first}\nbody", NOW)
    assert rel.startswith("Inbox/") and rel.count("/") == 1
    assert (tmp_path / rel).is_file()


def test_write_capture_content_and_collisions(tmp_path: Path) -> None:
    first = write_capture(tmp_path, tmp_path / "Inbox", "Idea\nbody", NOW)
    second = write_capture(tmp_path, tmp_path / "Inbox", "Idea\nother", NOW)
    assert first == "Inbox/2026-10-01 1432 Idea.md"
    assert second == "Inbox/2026-10-01 1432 Idea (2).md"
    content = (tmp_path / first).read_bytes().decode("utf-8")
    assert content == "---\ncaptured: 2026-10-01T14:32:05+02:00\nsource: app\n---\nIdea\nbody\n"


def test_write_capture_gives_up_after_99(tmp_path: Path) -> None:
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    (inbox / "2026-10-01 1432 Idea.md").write_text("x")
    for i in range(2, 100):
        (inbox / f"2026-10-01 1432 Idea ({i}).md").write_text("x")
    with pytest.raises(CaptureNameTaken):
        write_capture(tmp_path, inbox, "Idea", NOW)


def test_symlinked_capture_dir_outside_vault_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()
    try:
        (vault / "Inbox").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need extra privileges on this platform")
    with pytest.raises(OSError):
        write_capture(vault, vault / "Inbox", "x", NOW)
    assert not any(outside.iterdir())
```

`backend/tests/integration/test_capture_api.py` (with the same `make_api` fixture as Task 4):

```python
def test_capture_writes_and_worker_indexes(make_api, db_url, tmp_path, make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    fake = make_fake_ollama()
    client = make_api(vault_path=str(tmp_path / "Brain"), embed_url_override=fake.url)
    response = client.post("/api/capture", json={"text": "Zebra thought\nstripes"}, headers=SAME_ORIGIN)
    assert response.status_code == 201
    body = response.json()
    assert body["path"].startswith("Inbox/") and body["title"] == "Zebra thought"
    assert body["obsidian_url"].startswith("obsidian://open?vault=Brain&file=Inbox%2F")
    seed(db_url, tmp_path / "Brain", fake.url)
    assert [r["path"] for r in client.get("/api/search", params={"q": "stripes"}).json()["results"]] == [body["path"]]


def test_capture_errors(make_api, db_url, tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert make_api().post("/api/capture", json={"text": "x"}, headers=SAME_ORIGIN).json() == {"detail": "vault_disabled"}
    client = make_api(vault_path=str(tmp_path))
    assert client.post("/api/capture", json={"text": "  "}, headers=SAME_ORIGIN).status_code == 422
    assert client.post("/api/capture", json={"text": "a\x00"}, headers=SAME_ORIGIN).json() == {"detail": "invalid_text"}
    assert client.post("/api/capture", json={"text": "x" * 20001}, headers=SAME_ORIGIN).status_code == 422
    assert client.post("/api/capture", json={"text": "x"}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_capture_unwritable(make_api, db_url, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ai_second_brain.vault import capture as capture_module

    def boom(*args: object) -> str:
        raise PermissionError("denied /secret/path")

    monkeypatch.setattr(capture_module, "write_capture", boom)
    client = make_api(vault_path=str(tmp_path))
    assert client.post("/api/capture", json={"text": "x"}, headers=SAME_ORIGIN).json() == {"detail": "vault_unwritable"}
```

The route must call `capture_module.write_capture` through the module attribute, so the monkeypatch takes effect.

`backend/tests/integration/test_privacy_2b.py` extends the 2a privacy test pattern; open the existing 2a privacy test and copy its `caplog` setup. With `caplog.set_level(logging.DEBUG)` on the root, `ai_second_brain.*` and `procrastinate`, it:
1. seeds a vault with a note titled `SecretTitleQX`, containing `SecretBodyQX` under the path `Hidden/SecretPathQX.md`;
2. runs `GET /api/search?q=SecretQueryQX` and `GET /api/search?q=SecretBodyQX` (the second returns the note);
3. runs a private chat turn with `HybridRetriever` against the fake Ollama chat. Use the existing chat test helpers; if wiring a full turn is heavy, call `HybridRetriever.retrieve("SecretBodyQX question", 8)` directly;
4. sends `POST /api/capture` with `{"text": "SecretCaptureQX\nSecretCaptureBodyQX"}`.

Then it asserts that none of `SecretTitleQX`, `SecretBodyQX`, `SecretPathQX`, `SecretQueryQX` and `SecretCaptureQX` appears in `caplog.text`. The request-log middleware logs `request.url.path` only, not the query string; confirm this, and if it logs the query string, change it to log the path only.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend; uv run pytest tests/unit/test_capture_title.py -q`, then `cd ..; just backend::test tests/integration/test_capture_api.py tests/integration/test_privacy_2b.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`vault/capture.py`:

```python
"""Write a captured note into the vault: exclusive create, never overwrite, never outside."""

import os
import re
from datetime import datetime
from pathlib import Path

_FORBIDDEN = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f\x7f]')
MAX_TITLE = 60
MAX_SUFFIX = 99


class CaptureNameTaken(Exception):  # noqa: N818 - domain name, mapped to a 409 code
    pass


def capture_title(text: str) -> str:
    first = next((line for line in text.splitlines() if line.strip()), "")
    title = first.strip().lstrip("#").strip()
    title = " ".join(_FORBIDDEN.sub(lambda m: " " if m.group() in "\t" else "", title).split())
    if len(title) > MAX_TITLE:
        cut = title[:MAX_TITLE].rsplit(" ", 1)[0]
        title = cut if cut else title[:MAX_TITLE]
    title = title.rstrip(". ")
    return title or "Capture"


def write_capture(vault_root: Path, capture_dir: Path, text: str, now: datetime) -> str:
    capture_dir.mkdir(parents=True, exist_ok=True)
    root = vault_root.resolve()
    target_dir = capture_dir.resolve()
    if capture_dir.is_symlink() or not target_dir.is_relative_to(root):
        raise PermissionError("capture dir outside vault")
    stem = f"{now:%Y-%m-%d %H%M} {capture_title(text)}"
    body = f"---\ncaptured: {now.isoformat(timespec='seconds')}\nsource: app\n---\n{text.rstrip()}\n"
    for n in range(1, MAX_SUFFIX + 1):
        name = f"{stem}.md" if n == 1 else f"{stem} ({n}).md"
        path = target_dir / name
        try:
            with open(path, "x", encoding="utf-8", newline="\n") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            continue
        return path.relative_to(root).as_posix()
    raise CaptureNameTaken
```

A tab must map to a space, as in the `"tab\tand\x07bell"` case, while other control characters are removed. The lambda above handles both: `\t` is in the forbidden class, and the replacement gives `" "` only for `\t`. Keep it simple; if `ruff` complains, rewrite it as a small function. The expected outputs in the parametrized test are the contract.

`schemas.py`:

```python
class CaptureRequest(BaseModel):
    text: str = Field(max_length=20_000)


class CaptureResponse(BaseModel):
    path: str
    title: str
    obsidian_url: str | None
```

`routes/capture.py`:

```python
import asyncio
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ai_second_brain.interfaces.api.deps import get_settings, require_same_origin, require_session
from ai_second_brain.interfaces.api.schemas import CaptureRequest, CaptureResponse, ErrorResponse
from ai_second_brain.search.links import obsidian_url
from ai_second_brain.vault import capture as capture_module

logger = logging.getLogger("ai_second_brain.capture")
router = APIRouter(tags=["capture"], dependencies=[Depends(require_session)])
ERRORS: dict[int | str, dict[str, Any]] = {k: {"model": ErrorResponse} for k in (401, 403, 409, 422, 503)}


@router.post(
    "/capture", operation_id="captureNote", status_code=status.HTTP_201_CREATED,
    response_model=CaptureResponse, responses=ERRORS, dependencies=[Depends(require_same_origin)],
)
async def capture_note(body: CaptureRequest, request: Request) -> CaptureResponse:
    settings = get_settings(request)
    if settings.vault_path is None or settings.capture_dir is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="vault_disabled")
    if not body.text.strip() or "\x00" in body.text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_text")
    try:
        rel = await asyncio.to_thread(
            capture_module.write_capture, settings.vault_path, settings.capture_dir,
            body.text, datetime.now().astimezone(),
        )
    except capture_module.CaptureNameTaken:
        logger.info("capture outcome=capture_name_taken bytes=%d", len(body.text.encode()))
        raise HTTPException(status.HTTP_409_CONFLICT, detail="capture_name_taken") from None
    except OSError as error:
        logger.warning("capture outcome=vault_unwritable type=%s", type(error).__name__)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="vault_unwritable") from None
    logger.info("capture outcome=ok bytes=%d", len(body.text.encode()))
    return CaptureResponse(path=rel, title=capture_module.capture_title(body.text),
                           obsidian_url=obsidian_url(settings.obsidian_vault_name, rel))
```

Include the router in `app.py`. Add `captureNote` to the operation-id test if one exists.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: the tests above, then `just api-client`, `just backend::test`, `just check`.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend web/src/api
git commit -m "feat(api): capture notes into the vault inbox"
```

---

### Task 7: The web Search page

**Files:**
- Create: `web/src/features/search/{types.ts,api.ts,labels.ts,url.ts,SearchScreen.tsx,SearchScreen.test.tsx,labels.test.ts,url.test.ts}`
- Modify: `web/src/routes/_app/search.tsx`

**Interfaces:**
- Consumes: the generated `components["schemas"]` `SearchResponse`, `SearchHit` and `SearchFacets`; the paths `/api/search` and `/api/search/facets`; and `HttpError` / `statusOf` from `features/sources/api.ts`. Move them to `web/src/api/errors.ts` if that's cleaner, and update the Sources imports.
- Produces:
  - `SearchScreen` props (presentational):

    ```ts
    {
      state: SearchState;
      onState(next: SearchState): void;
      response?: SearchResponse;
      facets?: SearchFacets;
      loading: boolean;
      error?: number;
      recent: string[];
      onClearRecent(): void;
    }
    ```

  - `type SearchState = { q: string; folder?: string; tags: string[] }`.
  - Helpers:
    - `parseSearch(params: Record<string, unknown>): SearchState`;
    - `toSearchParams(state)`;
    - `snippetParts(snippet: string): { text: string; mark: boolean }[]`;
    - `errorCopy(status: number, detail?: string): string`;
    - `rememberQuery(q)` and `recentQueries()`, which use `localStorage` wrapped in try/catch.

- [ ] **Step 1: Write the failing tests**

`web/src/features/search/labels.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { errorCopy, snippetParts } from "./labels";

describe("snippetParts", () => {
  it("splits marks and decodes entities", () => {
    expect(snippetParts("a <mark>b</mark> &lt;c&gt; &amp;")).toEqual([
      { text: "a ", mark: false },
      { text: "b", mark: true },
      { text: " <c> &", mark: false },
    ]);
  });
  it("renders a script tag in a snippet as text", () => {
    expect(snippetParts("<script>x</script>")).toEqual([{ text: "<script>x</script>", mark: false }]);
  });
});

describe("errorCopy", () => {
  it("maps codes", () => {
    expect(errorCopy(409, "vault_disabled")).toBe("Set SB_VAULT_PATH to search your notes.");
    expect(errorCopy(503)).toBe("The database is unavailable. Try again in a moment.");
    expect(errorCopy(0)).toBe("Couldn't reach the server. Check your connection.");
  });
});
```

`web/src/features/search/url.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { parseSearch, toSearchParams } from "./url";

it("round-trips state through the URL", () => {
  const state = { q: "nas", folder: "Projects", tags: ["homelab", "nas"] };
  expect(parseSearch(toSearchParams(state))).toEqual(state);
  expect(parseSearch({ tag: "x" })).toEqual({ q: "", tags: ["x"] });
});
```

`web/src/features/search/SearchScreen.test.tsx` uses Testing Library, following the providers pattern of `SourcesScreen.test.tsx`. It should cover these cases:
1. The empty query shows the hint and the recent queries; "Clear" calls `onClearRecent`.
2. Typing debounces with fake timers: `onState` is not called before 250 ms, and is called with the new `q` at 250 ms. Enter calls it immediately.
3. Results render the title link (`href` = `obsidian_url`), the path, the heading trail `NAS › Dyski`, `<mark>` as a `mark` element, and the "Text" and "Meaning" badges.
4. `vector: "unavailable"` shows "Matching by meaning is unavailable right now; showing exact text matches."
5. No results with filters shows "No notes match. Try clearing the filters."
6. Tag chips toggle with `aria-pressed`, and "Clear filters" resets.
7. Arrow-down then Enter on the list opens the focused result's link: assert focus moves between result links.
8. A live region with `role="status"` reads "2 results".
9. A snippet containing `&lt;script&gt;` renders as the visible text `<script>`, and the document contains no `script` element.

Write each as an `it(...)` with concrete fixture data, for example:

```ts
const hit = (over: Partial<SearchHit> = {}): SearchHit => ({
  source_id: "00000000-0000-0000-0000-000000000001",
  path: "Projects/NAS.md",
  title: "NAS",
  heading_path: ["Dyski"],
  snippet: "Cztery <mark>dyski</mark>",
  matched: ["text"],
  score: 0.03,
  obsidian_url: "obsidian://open?vault=Brain&file=Projects%2FNAS.md",
  ...over,
});
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd web; pnpm vitest run src/features/search`
Expected: FAIL with missing modules.

- [ ] **Step 3: Implement**

`labels.ts`:

```ts
const ENTITIES: Record<string, string> = { "&lt;": "<", "&gt;": ">", "&amp;": "&", "&quot;": '"', "&#39;": "'" };
const decode = (s: string) => s.replace(/&(lt|gt|amp|quot|#39);/g, (m) => ENTITIES[m] ?? m);

/** Server snippets are escaped text with only <mark>…</mark>; anything else stays literal text. */
export function snippetParts(snippet: string): { text: string; mark: boolean }[] {
  const parts: { text: string; mark: boolean }[] = [];
  const re = /<mark>(.*?)<\/mark>/gs;
  let last = 0;
  for (const m of snippet.matchAll(re)) {
    if (m.index > last) parts.push({ text: decode(snippet.slice(last, m.index)), mark: false });
    parts.push({ text: decode(m[1] ?? ""), mark: true });
    last = m.index + m[0].length;
  }
  if (last < snippet.length) parts.push({ text: decode(snippet.slice(last)), mark: false });
  return parts.filter((p) => p.text.length > 0);
}

export const VECTOR_UNAVAILABLE = "Matching by meaning is unavailable right now; showing exact text matches.";

export function errorCopy(status: number, detail?: string): string {
  if (status === 409 && detail === "vault_disabled") return "Set SB_VAULT_PATH to search your notes.";
  if (status === 503) return "The database is unavailable. Try again in a moment.";
  if (status === 401) return "Your session ended. Sign in again.";
  if (status === 0) return "Couldn't reach the server. Check your connection.";
  return "Search failed. Try again.";
}

const RECENT_KEY = "sb.search.recent";
export function recentQueries(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const list: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list.filter((x): x is string => typeof x === "string").slice(0, 10) : [];
  } catch {
    return [];
  }
}
export function rememberQuery(q: string): void {
  try {
    const next = [q, ...recentQueries().filter((x) => x !== q)].slice(0, 10);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable: recent searches are a convenience */
  }
}
export function clearRecent(): void {
  try {
    localStorage.removeItem(RECENT_KEY);
  } catch {
    /* ignore */
  }
}
```

The `errorCopy` strings above must match the Sources screen's copy where the codes overlap. Check `features/sources/labels.ts` and reuse its exact strings for 503, 401 and 0 if they differ, then update these tests to match.

`url.ts`:

```ts
export type SearchState = { q: string; folder?: string; tags: string[] };

export function parseSearch(params: Record<string, unknown>): SearchState {
  const q = typeof params.q === "string" ? params.q : "";
  const folder = typeof params.folder === "string" && params.folder ? params.folder : undefined;
  const raw = params.tag;
  const tags = (Array.isArray(raw) ? raw : raw === undefined ? [] : [raw]).filter(
    (t): t is string => typeof t === "string" && t.length > 0,
  );
  return folder ? { q, folder, tags } : { q, tags };
}

export function toSearchParams(state: SearchState): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (state.q) out.q = state.q;
  if (state.folder) out.folder = state.folder;
  if (state.tags.length) out.tag = state.tags;
  return out;
}
```

`api.ts`:

```ts
import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "@/api/client";
import { HttpError } from "@/features/sources/api";
import type { SearchState } from "./url";

export class SearchHttpError extends HttpError {
  constructor(status: number, readonly detail?: string) {
    super(status);
  }
}

export function searchQueryOptions(state: SearchState) {
  return queryOptions({
    queryKey: ["search", state] as const,
    enabled: state.q.trim().length >= 2,
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/search", {
        params: { query: { q: state.q, folder: state.folder, tag: state.tags.length ? state.tags : undefined } },
      });
      if (!data) throw new SearchHttpError(response.status, (error as { detail?: string } | undefined)?.detail);
      return data;
    },
  });
}

export const facetsQueryOptions = queryOptions({
  queryKey: ["search", "facets"] as const,
  staleTime: 60_000,
  queryFn: async () => {
    const { data, response } = await api.GET("/api/search/facets");
    if (!data) throw new HttpError(response.status);
    return data;
  },
});
```

`SearchScreen.tsx` is presentational and built from the existing design-system `Input`, `Button` and `Card` components. Its layout follows spec §8:
- a heading "Search";
- a query input (`aria-label="Search your notes"`, autofocus) that holds its own local text state and calls `onState({...state, q})` 250 ms after the last keystroke, or immediately on Enter;
- a `/` key handler on `document`, which focuses the input unless the event target is an input or textarea;
- a folder `<select>` (`aria-label="Folder"`);
- tag chips as `<button aria-pressed>` (top 12), with "More…" opening a `<details>` holding a filter input and the remaining tags. A native `<details>` is enough, so no new popover dependency is needed;
- "Clear filters";
- the `role="status"` live region;
- the results as `<ol>`. Each `<li>` holds an `<a href={obsidian_url}>` title (plain text if the URL is null), the path in `font-mono`, the heading trail, the snippet built from `snippetParts` (`mark` → `<mark className="bg-accent-subtle text-fg">`; use tokens from `tokens.css`), and the badges "Text" / "Meaning". ArrowDown and ArrowUp on the list move focus between result links.
- States, per spec §8: empty, loading (`aria-busy` and `opacity-60` on the list), no results, `vector` unavailable, and error via `errorCopy`.

`routes/_app/search.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { statusOf } from "@/features/sources/api";
import { facetsQueryOptions, SearchHttpError, searchQueryOptions } from "@/features/search/api";
import { clearRecent, recentQueries, rememberQuery } from "@/features/search/labels";
import { SearchScreen } from "@/features/search/SearchScreen";
import { parseSearch, toSearchParams } from "@/features/search/url";

export const Route = createFileRoute("/_app/search")({
  validateSearch: (raw: Record<string, unknown>) => toSearchParams(parseSearch(raw)),
  component: SearchRoute,
});

function SearchRoute() {
  const state = parseSearch(Route.useSearch());
  const navigate = useNavigate({ from: Route.fullPath });
  const search = useQuery(searchQueryOptions(state));
  const facets = useQuery(facetsQueryOptions);
  const [recent, setRecent] = useState(recentQueries);
  useEffect(() => {
    if (search.data && state.q.trim()) {
      rememberQuery(state.q.trim());
      setRecent(recentQueries());
    }
  }, [search.data, state.q]);
  const error = search.error;
  return (
    <SearchScreen
      state={state}
      onState={(next) => navigate({ search: toSearchParams(next), replace: true })}
      response={search.data}
      facets={facets.data}
      loading={search.isFetching}
      error={error ? statusOf(error) : undefined}
      errorDetail={error instanceof SearchHttpError ? error.detail : undefined}
      recent={recent}
      onClearRecent={() => {
        clearRecent();
        setRecent([]);
      }}
    />
  );
}
```

Add `errorDetail?: string` to the props in Step 1's interface and to the tests. Run `pnpm exec tsr generate` if this repo needs the route tree regenerated (check `package.json` scripts; the Vite plugin usually does it).

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd web; pnpm vitest run src/features/search`, then `cd ..; just check`.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "feat(web): add the search page"
```

---

### Task 8: Capture dialog, chat source links, and the receipt note

**Files:**
- Create: `web/src/design-system/ui/dialog.tsx`, `web/src/features/capture/{CaptureDialog.tsx,api.ts,labels.ts,draft.ts,CaptureDialog.test.tsx}`
- Modify: `web/package.json` (`@radix-ui/react-dialog`), `web/src/design-system/AppShell.tsx` (+ test), `web/src/features/chat/components/SourceList.tsx`, the component that renders the receipt (find it with `grep -rn "duration_ms\|receipt" web/src/features/chat`), and `components.test.tsx`

**Interfaces:**
- Consumes: `POST /api/capture` (Task 6), and `Source.obsidian_url` / `ReceiptEvent.retrieval` (Task 5).
- Produces: `CaptureDialog({ open, onOpenChange })`. `AppShell` renders the Capture button and the `c` shortcut.

- [ ] **Step 1: Add the dependency**

Run: `cd web; pnpm add @radix-ui/react-dialog`

`design-system/ui/dialog.tsx` follows the existing `alert-dialog.tsx` styling:

```tsx
import * as DialogPrimitive from "@radix-ui/react-dialog";
import type { ComponentProps } from "react";
import { cn } from "@/design-system/cn";

export const Dialog = DialogPrimitive.Root;
export const DialogTitle = DialogPrimitive.Title;
export const DialogDescription = DialogPrimitive.Description;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({ className, ...props }: ComponentProps<typeof DialogPrimitive.Content>) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 bg-fg/40" />
      <DialogPrimitive.Content
        className={cn(
          "fixed top-1/2 left-1/2 w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-surface-raised p-6 shadow-lg",
          className,
        )}
        {...props}
      />
    </DialogPrimitive.Portal>
  );
}
```

- [ ] **Step 2: Write the failing tests**

`CaptureDialog.test.tsx` uses the repo's render-with-QueryClient helper; look at existing tests and mock the API with the same approach chat and Sources tests use (`vi.mock("@/api/client")` or MSW, whichever is in use). The cases are:
1. Typing then `Ctrl+Enter` posts `{text}`. On 201 it shows the status "Saved to Inbox" with an "Open in Obsidian" link to `obsidian_url`, closes the dialog, and clears the draft.
2. With an empty text, the Save button is disabled.
3. A 503 `vault_unwritable` keeps the text and shows "Couldn't write to the vault folder."
4. A 409 `vault_disabled` shows "No vault is configured. Set SB_VAULT_PATH."
5. A 409 `capture_name_taken` shows "Too many captures with this title this minute."
6. The draft persists: type, close, reopen, and the text is still there (`localStorage` key `sb.capture.draft`).

In `AppShell.test.tsx`:
- pressing `c` with focus on `body` opens the dialog;
- pressing `c` inside an input does not;
- the "Capture" button opens it.

In `components.test.tsx`:
- a source with `obsidian_url` renders its path as a link with that `href`;
- without a URL it renders no link;
- a receipt with `retrieval: "text_only"` shows "Searched your notes (text only)".

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `cd web; pnpm vitest run src/features/capture src/design-system src/features/chat`
Expected: FAIL.

- [ ] **Step 4: Implement**

`features/capture/draft.ts`:

```ts
const KEY = "sb.capture.draft";
export function loadDraft(): string {
  try {
    return localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}
export function saveDraft(text: string): void {
  try {
    if (text) localStorage.setItem(KEY, text);
    else localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable */
  }
}
```

`features/capture/labels.ts`:

```ts
export function captureErrorCopy(status: number, detail?: string): string {
  if (detail === "vault_disabled") return "No vault is configured. Set SB_VAULT_PATH.";
  if (detail === "vault_unwritable") return "Couldn't write to the vault folder.";
  if (detail === "capture_name_taken") return "Too many captures with this title this minute.";
  if (status === 0) return "Couldn't reach the server. Check your connection.";
  return "Couldn't save the note. Try again.";
}
```

`features/capture/api.ts`:

```ts
import { api } from "@/api/client";

export type CaptureResult =
  | { ok: true; path: string; title: string; obsidian_url: string | null }
  | { ok: false; status: number; detail?: string };

export async function captureNote(text: string): Promise<CaptureResult> {
  try {
    const { data, error, response } = await api.POST("/api/capture", { body: { text } });
    if (data) return { ok: true, ...data };
    return { ok: false, status: response.status, detail: (error as { detail?: string } | undefined)?.detail };
  } catch {
    return { ok: false, status: 0 };
  }
}
```

`CaptureDialog.tsx` behaves as follows:
- It holds `text` state, initialised from `loadDraft()`, and saves the draft on change.
- It holds a `saving` flag, and an `error` string or null.
- On save it calls `captureNote`. On success it calls `saveDraft("")` and `setText("")`, closes the dialog via `onOpenChange(false)`, and calls an `onSaved(result)` prop.
- `AppShell` renders the success status line ("Saved to Inbox" plus the link) in a `role="status"` region in the header for 6 s, so it outlives the dialog.
- The textarea is `aria-label="Note"`, autofocused, and handles `onKeyDown` for `(e.ctrlKey || e.metaKey) && e.key === "Enter"`.
- The error appears in `<p role="alert">`.
- Buttons: "Save" (disabled when `!text.trim() || saving`) and "Cancel".

In `AppShell.tsx`, add a "Capture" `Button` (lucide `PenLine` icon) before `ThemeToggle`, plus:

```tsx
useEffect(() => {
  function onKey(e: KeyboardEvent) {
    const t = e.target as HTMLElement | null;
    const typing = t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
    if (e.key === "c" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      setCaptureOpen(true);
    }
  }
  document.addEventListener("keydown", onKey);
  return () => document.removeEventListener("keydown", onKey);
}, []);
```

`SourceList.tsx`: wrap the path in `<a href={source.obsidian_url} className="font-mono break-all underline-offset-2 hover:underline">` when `source.obsidian_url` is present, and keep the `<span>` otherwise.

In the receipt component, when `receipt.retrieval === "text_only"`, append the muted text "Searched your notes (text only)".

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `cd web; pnpm vitest run`, then `cd ..; just check`.
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web
git commit -m "feat(web): add capture and link chat sources to Obsidian"
```

---

### Task 9: End to end

**Files:**
- Create: `web/tests/e2e/search.spec.ts`
- Modify:
  - `backend/tests/e2e_reset.py` (remove the fixture `Inbox/`);
  - `web/tests/e2e/fixtures/vault/.gitignore` (`Inbox/`);
  - `web/tests/e2e/fixtures/fake-ollama.ts`, only if chat needs an answer that cites `[1]`. The existing chat answer path is reused;
  - `web/playwright.config.ts`, only if `SB_OBSIDIAN_VAULT` or `SB_CAPTURE_DIR` must be set; the defaults should do.

**Interfaces:**
- Consumes: everything above, plus the 2a e2e stack (API, web, worker, fake Ollama, fixture vault).

- [ ] **Step 1: Reset the inbox**

Append to `backend/tests/e2e_reset.py`, before the final print:

```python
import shutil
from pathlib import Path

vault = os.environ.get("SB_VAULT_PATH")
if vault:
    shutil.rmtree(Path(vault) / os.environ.get("SB_CAPTURE_DIR", "Inbox"), ignore_errors=True)
```

Move the imports to the top. Create `web/tests/e2e/fixtures/vault/.gitignore` containing `Inbox/`. The worker excludes nothing extra here, and `.gitignore` is not a `.md` file, so it is never indexed.

- [ ] **Step 2: Write the spec**

`web/tests/e2e/search.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

const PASSWORD = "e2e-test-password";

test.beforeEach(async ({ page }) => {
  await page.goto("/search");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/search/);
});

test("search finds a note by text and filters by tag", async ({ page }) => {
  const box = page.getByRole("searchbox", { name: "Search your notes" }).or(page.getByLabel("Search your notes"));
  await box.fill("Dyski");
  const results = page.getByRole("list", { name: "Search results" });
  await expect(results.getByText("Projects/NAS.md")).toBeVisible({ timeout: 60_000 });
  await expect(results.locator("mark", { hasText: /dyski/i }).first()).toBeVisible();
  await page.getByRole("button", { name: "homelab", pressed: false }).click();
  await expect(page).toHaveURL(/tag=homelab/);
  await expect(results.getByRole("listitem")).toHaveCount(1);
});

test("a capture becomes searchable", async ({ page }) => {
  await page.getByRole("button", { name: "Capture" }).click();
  await page.getByLabel("Note").fill("Test capture e2e\nzebrafish marker");
  await page.keyboard.press("Control+Enter");
  await expect(page.getByText("Saved to Inbox")).toBeVisible();
  const box = page.getByLabel("Search your notes");
  await expect(async () => {
    await box.fill("");
    await box.fill("zebrafish");
    await expect(page.getByRole("list", { name: "Search results" }).getByText(/Inbox\/.*Test capture e2e\.md/))
      .toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 45_000 });
});

test("private chat cites the NAS note", async ({ page }) => {
  await page.goto("/ask");
  // Use the same steps chat.spec.ts uses to start a private session and send a question.
  // Question: "Kiedy są kopie zapasowe na NAS?"
  // Then:
  await expect(page.getByRole("region", { name: "Sources" }).getByText("Projects/NAS.md")).toBeVisible({ timeout: 30_000 });
});
```

Finish the chat test by copying the session-start and send steps from `web/tests/e2e/chat.spec.ts` verbatim. Write out the exact steps; leave no comments behind.

The question's terms `kopie`, `zapasowe` and `nas` give the NAS chunk a text hit (≥2 terms), so it is cited whatever the fake vectors are. Give the results `<ol>` the attribute `aria-label="Search results"` in Task 7's `SearchScreen` (amend it there if it's missing), and the sources `<section>` already has `aria-label="Sources"`.

- [ ] **Step 3: Run it twice**

Run: `just e2e` twice.
Expected: all specs pass both times, and `git status` shows no `Inbox/` files.

- [ ] **Step 4: Commit**

```bash
git add web/tests/e2e backend/tests/e2e_reset.py
git commit -m "test(e2e): search, capture and cited chat"
```

---

### Task 10: Benchmark, docs, screenshots and final checks

**Files:**
- Create: `backend/scripts/search_bench.py`, `docs/images/readme/search.jpg`, `docs/images/readme/ask-sources.jpg`
- Modify:
  - `README.md`;
  - `docs/architecture/system-design.md` §9;
  - `docs/architecture/adr/0012-salience-without-popularity-bias.md`;
  - `web/tests/e2e/readme-screenshots.spec.ts` (two opt-in shots);
  - `.env.example` (four new settings, commented).

- [ ] **Step 1: The benchmark script**

`backend/scripts/search_bench.py`:

```python
"""p50/p95 of hybrid search over a synthetic 50k-chunk set. Needs an empty scratch database.

Usage: uv run python scripts/search_bench.py postgres://…/scratch_db
"""

import asyncio
import random
import statistics
import sys
import time

from psycopg import AsyncConnection

from ai_second_brain.runtime import new_event_loop
from ai_second_brain.search.query import query

WORDS = "nas dysk kopia backup proxmox klaster sieć router vlan zfs raid docker host serwer".split()


def vec(rng: random.Random) -> list[float]:
    values = [rng.gauss(0, 1) for _ in range(1024)]
    norm = sum(v * v for v in values) ** 0.5
    return [v / norm for v in values]


async def seed(conn: AsyncConnection, rng: random.Random, notes: int = 5000, chunks_per_note: int = 10) -> None:
    async with conn.transaction():
        for n in range(notes):
            src = await (await conn.execute(
                "INSERT INTO sources (kind, external_ref, title) VALUES ('obsidian', %s, %s) RETURNING id",
                (f"bench/n{n}.md", f"n{n}"),
            )).fetchone()
            rev = await (await conn.execute(
                "INSERT INTO source_revisions (source_id, content_hash, raw_text, state, tags)"
                " VALUES (%s, %s, '', 'indexed', %s) RETURNING id",
                (src[0], rng.randbytes(32), [rng.choice(WORDS)]),
            )).fetchone()
            await conn.execute("UPDATE sources SET current_revision_id = %s WHERE id = %s", (rev[0], src[0]))
            for c in range(chunks_per_note):
                text = " ".join(rng.choice(WORDS) for _ in range(120)) + f" host{n:05d}"
                chunk = await (await conn.execute(
                    "INSERT INTO chunks (revision_id, ordinal, content) VALUES (%s, %s, %s) RETURNING id",
                    (rev[0], c, text),
                )).fetchone()
                await conn.execute(
                    "INSERT INTO chunk_embeddings (chunk_id, space_id, embedding) VALUES (%s, 1, %s::halfvec)",
                    (chunk[0], str(vec(rng))),
                )


async def main(url: str) -> None:
    rng = random.Random(7)
    async with await AsyncConnection.connect(url) as conn:
        await seed(conn, rng)
        await conn.execute("ANALYZE")
        timings = []
        for i in range(200):
            q = f"host{rng.randrange(5000):05d}" if i % 2 else " ".join(rng.sample(WORDS, 2))
            started = time.perf_counter()
            await query(conn, q, vector=vec(rng), limit=20)
            timings.append((time.perf_counter() - started) * 1000)
    timings.sort()
    print(f"p50={statistics.median(timings):.1f}ms p95={timings[int(len(timings) * 0.95)]:.1f}ms")


if __name__ == "__main__":
    loop = new_event_loop()
    loop.run_until_complete(main(sys.argv[1]))
```

Run it against a scratch database created and migrated the same way the test database is. Record the p50/p95 in the README's architecture notes, along with the machine. Do not commit any database. If p95 ≥ 400 ms, report it as a concern with the `EXPLAIN ANALYZE` of the slowest query, and do not tune blindly.

- [ ] **Step 2: Screenshots**

Append two opt-in tests to `readme-screenshots.spec.ts`, gated by `README_SHOTS` like the existing ones:
- `search.jpg`: `/search?q=dyski` at 1280×800, waiting for `Projects/NAS.md` in the results.
- `ask-sources.jpg`: a private chat turn asking about the NAS backups, waiting for the Sources region to show `Projects/NAS.md`.

Run them with `README_SHOTS=1` (in PowerShell: `$env:README_SHOTS='1'; pnpm exec playwright test readme-screenshots`). Open both images with the Read tool and check them.

- [ ] **Step 3: The docs**

- **README.md:**
  - **"What it does today":**
    - **Search:** hybrid search, exact identifiers plus meaning, folder and tag filters, and results that open in Obsidian.
    - **Private chat:** answers cite your notes.
    - **Capture:** the `c` key or the Capture button writes `Inbox/…md`.
  - **Screenshots:** `search.jpg` and `ask-sources.jpg`.
  - **Settings:** table rows for `SB_CAPTURE_DIR`, `SB_OBSIDIAN_VAULT`, `SB_CHAT_NUM_CTX` and `SB_RETRIEVAL_MIN_SIMILARITY`, with the defaults and ranges from the Global Constraints.
  - **Keys:** `/` focuses search, `c` opens capture, `Ctrl+Enter` saves a capture.
  - **The Obsidian link:** it needs Obsidian installed on the device that opens it.
  - **Troubleshooting:**
    - "Matching by meaning is unavailable": the embedding host is unreachable or the model is missing; see 2a.
    - "Couldn't write to the vault folder": the API needs write access to `SB_VAULT_PATH/SB_CAPTURE_DIR`.
  - **Roadmap:** 2b ✅.
- **`system-design.md` §9:** 2b is **delivered**, linking the spec.
- **ADR-0012:** add a short "Status note (Phase 2b)". Search ranks by RRF only, and the salience prior arrives with Phase 7.
- **`.env.example`:** the four settings, commented, with their defaults.

- [ ] **Step 4: Final verification**

Run from the repository root: `just check`, `just test`, `just e2e`.
Expected: all pass. The owner then does the real-vault check: `just dev`, search, a cited chat answer, and a capture.

- [ ] **Step 5: Commit**

```bash
git add README.md docs .env.example backend/scripts web/tests/e2e/readme-screenshots.spec.ts
git commit -m "docs: document search, cited chat and capture"
```

The owner pushes once after the final whole-branch review. CI releases v0.5.0.
