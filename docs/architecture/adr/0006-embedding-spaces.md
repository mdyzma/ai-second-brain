# ADR-0006: Versioned embedding spaces and a multilingual default

**Status:** Accepted (2026-09-30)
**Date:** 2026-09-29
**Deciders:** Michal Dyzma

## Context

The discarded MVP used `all-MiniLM-L6-v2` (384-d, English-centric). The prompt alternates between 1536-d (OpenAI) and 1024-d (bge-m3). Notes are Polish and English. OpenAI embeddings would send private text to a cloud API, which is incompatible with the privacy constraint.

## Decision

1. Store embeddings in `chunk_embeddings(chunk_id, space_id, embedding halfvec)` with an `embedding_spaces` registry. Each space gets one partial expression HNSW index (`(embedding::halfvec(N)) ... WHERE space_id = K`). Never compare vectors across spaces.
2. Serve embeddings through **Ollama's `/api/embed`**. The backend stays free of torch, and the model is swappable by config ([ADR-0011](0011-backend-language-python-vs-typescript.md)).
3. Choose the first default by a quick bake-off in the Python eval harness on a labelled PL/EN retrieval set. Candidates: `bge-m3` (1024-d, multilingual) and a `multilingual-e5` variant, with MiniLM as the baseline. Expected default: bge-m3.
4. Cloud embedding APIs are not used.

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| **A. Versioned spaces (chosen)** | Zero-downtime model swaps; A/B retrieval | Slightly more complex queries |
| B. Single `vector(N)` column, re-embed in place | Simplest schema | Downtime/mixed state during re-embed; no comparison |
| C. MiniLM (MVP model) | Small, fast | Weak Polish recall (unmeasured but likely) |
| D. OpenAI `text-embedding-3` 1536-d | Strong quality | Private text leaves the LAN — rejected |

## Consequences

- Easier: trying a new model is "create space, backfill job, compare, flip default".
- Harder: backfill jobs over ~0.5 M chunks (bge-m3 on CPU: hours; schedule on the GPU host at night).
- Revisit: drop the non-default space after one month on the new default to reclaim space.

**Note (Phase 2a):** Space 1 is bge-m3 (1024-d) from Phase 2a; the bake-off against MiniLM/e5 moves to Phase 3 as an evaluation of this default.

**Phase 3 (2026-10-02):** The bake-off harness exists ([spec](../../superpowers/specs/2026-10-02-phase-3-embedding-evaluation-design.md)). It replaces the MiniLM/e5 candidates above with the incumbent `bge-m3` against `snowflake-arctic-embed2`, `granite-embedding:278m` and `paraphrase-multilingual`, run on the owner's own PL/EN questions. A challenger wins only if its hybrid recall@10 ≥ the incumbent's + 0.05, its hybrid MRR@10 ≥ the incumbent's, and its query-embedding p95 < 300 ms. **Result (2026-10-03): bge-m3 stays** — no challenger met the win rule, so Phase 3b is not needed. Before the run, a second space is added (Phase 3b) only if a challenger wins. Each model gets the query prefix its model card prescribes (only `snowflake-arctic-embed2` has one: `query: `). A winning model with a prefix must get the same prefix in production search and chat in Phase 3b.

## Action Items
1. [ ] Build the labelled retrieval set (50 queries, PL/EN, known target notes) — reusable by Phase 0.
2. [ ] Backfill job with checkpointing and progress in `doctor`.
