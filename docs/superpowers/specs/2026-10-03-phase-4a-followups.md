# Phase 4a follow-ups

Known limitations and deferred minors from the Phase 4a (knowledge graph) build. None of them blocks use. Pick them up in Phase 4b or later, when one starts to hurt on the real vault.

## Accepted limitations

- **Shared machine edges flicker.** A proposed or auto entity–entity edge that two notes both produce is deleted when one of them is re-extracted. It returns when the other note is re-extracted.
- **Alias-named relations are dropped at extraction.** The output filter only keeps relations whose endpoints are entity names in the same output. A relation that names an entity by an alias is dropped, even though resolve could handle it.
- **Extraction's parent check covers 2-cycles only.** `set_proposed_parent` refuses A→B→A. A longer cycle formed with the owner's `set_parent` is possible. The owner's `set_parent` itself refuses any cycle.

## Deferred from the final review

- **M3. One error class for every endpoint failure.** Every failure is classed as `extract_unreachable`, and the retry window is about 18.5 minutes (30+60+120+300+600 s). A long Ollama outage leaves failed rows. `just graph-extract --failed` recovers them.
- **M4. Name matching uses the interactive embedder.** It uses the query embedder with its 1.5 s timeout. A busy GPU can time out name vectors. Those entities then skip the "similar" step and come in as proposed.
- **M7. A merge that races extraction fails the job without writing an extraction row.** The note is picked up again as pending on the next run.
- **M8. Merging a proposed duplicate into an accepted entity floods Links.** The loser's proposed mention edges move over, one Links row each.

## Deferred from task reviews

- **Concurrency coverage.**
  - The race between creating an alias and creating a same-name entity is untested; only a sequential test exists.
  - There are no concurrency tests for owner decisions.
- **Prompt and client.**
  - `</ note>` spacing variants are not neutralised.
  - Malformed-200 parsing and `read_timeout` are untested at the client level.
- **Resolve:** no test for the rejected check running before the suggested alias.
- **Worker:** no test for the supervisor log line or for a tight crash loop.
- **Queries at scale.**
  - `list_entities` runs a count subquery per page.
  - Entity suggestions do an exact scan with no ANN index on `entity_embeddings`. Both are fine at personal scale.
- **Web.**
  - The entities error copy is derived from the review copy by string replace.
  - The Projects nav item is never active because it redirects.
  - There are no router-level redirect, `validateSearch` round-trip or load-more tests.
- **E2E:** the readiness wait is keyed on `revisions.total >= 5`, the number of fixture notes.
