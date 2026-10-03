# ADR-0013: A knowledge graph the owner decides: extract locally, propose, then review

**Status:** Accepted (2026-10-03)
**Date:** 2026-10-03
**Deciders:** Michal Dyzma

## Context

Phase 4 turns indexed notes into a graph of the things they talk about, so that an entity page can list the notes that mention a device, a person or a project. The [system design §3](../system-design.md#3-data-model-ltm) sketched `entities` and `edges` tables but not how they are filled. A language model fills them, and a language model is wrong in three predictable ways:

| # | Failure | Effect on the graph |
|---|---|---|
| 1 | **Invented or noisy entities** ("the meeting", a heading, a typo) | A graph the owner stops trusting |
| 2 | **Duplicates** ("NAS", "Synology NAS", "nas") | Fragmented pages, wrong counts |
| 3 | **Unstable output.** A re-run on the same note gives a different answer | A decision the owner made last week silently changes |

Extraction also reads every note, so it is bound by the same privacy rule as chat: private text goes only to the Ollama endpoints the owner configured ([ADR-0005](0005-local-inference-topology.md)). Phase 4 is split: **4a** (this ADR, [spec](../../superpowers/specs/2026-10-03-phase-4a-knowledge-graph-design.md)) is the graph and its review; **4b** adds the nightly schedule and the morning digest.

## Decision

1. **Six entity types and six relations.** Types: `project`, `person`, `organization`, `tool`, `device`, `topic`. Relations: `mentions`, `about`, `uses`, `runs_on`, `works_with`, `part_of`. Both are closed sets, enforced in the schema and in the database (`entity_type` enum, a `CHECK` on `relation`). An unknown type or relation from the model is dropped, not stored.
2. **Extraction is local only, one job per note, on the lowest-priority queue.** The job `graph_extract_revision(revision_id)` calls the local model named by `SB_EXTRACT_MODEL` (default: the model of the first local chat endpoint; hosted `:cloud` tags are refused). It runs in its own worker loop on the `extract` queue with concurrency 1, beside the ingest/embed loop (concurrency 2), so indexing and embedding stay fast. With no local endpoint, extraction is disabled and the API says so.
3. **Auto-accept is narrow.** A note-to-entity link (`mentions` or `about`) is accepted automatically only when all three hold: the entity is already `accepted`, the match was exact or through an alias (not an embedding match and not a new entity), and the confidence is at least `SB_EXTRACT_AUTO_ACCEPT` (0.8). Everything else is `proposed`. New entities are always proposed, and relations between entities are never auto-accepted.
4. **Propose, then the owner decides.**
   - The owner's decisions are never overwritten. Edges carry `decided_by` (`auto` or `user`); re-extraction replaces only machine edges (`origin` `llm:...`, `decided_by='auto'`) and never changes the status of a user-decided one.
   - **Rejected names are remembered.** A rejected entity stays in the table, and a later mention of its name or alias is dropped, with every relation that names it. The model cannot bring it back.
   - **A merge keeps the losing name as an alias** of the winner, moves its edges and children, and only works within one type.
   - Rename, retype and re-parent are owner actions too. A re-parent that would form a 2-cycle is refused (`parent_cycle`).
5. **Entities are never deleted by extraction.** A proposed entity whose last edge disappeared is still listed in Review, with zero mentions.
6. **`EXTRACTOR_VERSION` drives re-extraction.** It is a code constant, bumped when the prompt, schema or merge rules change. A note is extracted once per version, so bumping it makes every note eligible again, and a normal run (`just graph-extract`) skips the notes already done. A failed row for the current version is retried only with `--failed`.
7. **Duplicates are caught by exact match, aliases and name embeddings.** A new name is matched, in order, by exact normalised name or alias, then by the nearest same-type entity whose name embedding has cosine similarity of at least `SB_ENTITY_MATCH_SIMILARITY` (0.90). An embedding match links to the existing entity but is recorded as `similar`, so it is never auto-accepted, and the extracted name is offered in Review as an alias.

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| **A. Propose, then the owner decides; auto-accept only for known entities (chosen)** | The graph is trusted; decisions are stable; review effort falls as the graph grows | The first run needs a review pass |
| B. Accept everything the model extracts | No review work | Failures 1 and 2 land in the graph; nothing to trust |
| C. Review everything, including every link to accepted entities | Maximal control | A queue that never empties; the owner stops reviewing |
| D. A cloud model for better extraction | Better recall | Private note text leaves the LAN. Rejected |
| E. Overwrite the graph on every extraction | Simple; always current | Failure 3: owner decisions are lost |
| F. A graph database | Native traversal | A second datastore for 2-3 hop queries that recursive CTEs cover ([ADR-0002](0002-postgres-single-datastore.md)) |

## Consequences

- Easier: the graph is something the owner has looked at. Entity pages and the Projects navigation can rely on accepted entities only.
- Harder: the first extraction is a model call per note, behind indexing and embedding, followed by one review pass. After that, only new entities need attention.
- The queue refreshes itself: the status poll runs every 5 s while extract jobs are queued and every 60 s otherwise.
- **Known, accepted limitations:**
  - A proposed or auto edge shared by two notes is dropped when one of them is re-extracted, and returns when its own note is re-extracted.
  - A relation whose subject or object is named by an alias is dropped by the output filter.
  - The parent-cycle check covers only 2-cycles.
- Revisit: when 4b adds the nightly run, decide whether it re-extracts on `EXTRACTOR_VERSION` bumps by itself; when salience arrives (Phase 7), decide how accepted entities feed ranking, without making popular entities win ([ADR-0012](0012-salience-without-popularity-bias.md)).
