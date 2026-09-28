# Second Brain: project comparison and design critique

Date: 2026-09-29. Evidence: repository at `db40cae`, including the existing untracked `docs/second-brain-prompt.md`. This is a source review; the database, hardware, model quality, and rendered terminal were not exercised. External projects listed in the prompt were not evaluated and their promotional claims are not evidence.

## Intended outcome

The prompt describes a personal, self-hosted assistant that connects notes, engineering history, personal documents, and hardware context while keeping private information local. Success means useful, traceable retrieval and explicit, reliable actions. Biological memory terms are a metaphor; they do not establish retrieval quality or justify deleting information.

The recommendation is to deliver this through separate specs. The first planning unit is [private chat routing](2026-09-29-private-chat-routing-design.md). This prioritization is proposed, not an approved change to the full product vision.

## Implementation versus prompt

| Capability | Repository evidence | Gap and disposition |
|---|---|---|
| Local semantic retrieval | `ltm/embedder.py`, `ltm/retriever.py`, `ltm/db_manager.py`: local sentence-transformers, cosine search, source formatting | Present; relevance and multilingual quality unmeasured |
| Persistent LTM | `sql_migrations/V1__init_schema.sql`: `agent_memories`, vector(384), HNSW | Present as flat memory; no project/skill/financial graph |
| Conversational STM | `core/agent.py`: process-local message list | Present but unbounded; no durable sessions or consolidation |
| Staged ingestion | V1 creates `short_term_memory`; `stm/__init__.py` has no pipeline | Table alone does not implement STM ingestion |
| Obsidian | `src/second_brain/tools/obsidian_sync.py`: modified-file callback, paragraph chunks, immediate LTM writes | No initial scan, create/delete/move handling, durable queue, or reconciliation |
| Safe note replacement | Sync calls committed `delete_by_source` before embedding, then commits each insertion | Embedding failure loses previous searchable version; partial inserts possible |
| Local/cloud isolation | `Agent` always constructs Anthropic client and appends retrieved context to sent history | Missing; highest-priority gap against explicit privacy constraint |
| Sleep and limbo | No workers or counters | Missing; needs defined events, idempotency, retention and recovery |
| Financial, email and git ingestion | No parsers or related schema | Missing; separate ingestion specs |
| Hardware and project environments | No SSH, WoL, node schema or Proxmox adapter | Missing; deployment assumptions unverified |
| Omni-search and API | Click CLI only | No FastAPI, compound request executor or relational filters |
| MCP | README suggests external integration | No repository MCP server or host; prompt samples simulate responses |
| Testing | Agent/retriever mocks, configuration tests, real embedder tests | No database integration, watcher recovery, privacy boundary or hardware tests |

Paths in this table are relative to `src/second_brain` where abbreviated. The empty `tools/notes_dump.py` is not an ingestion implementation; the root `tools/obsidian_sync.py` is a separate legacy script with hard-coded configuration.

## Critical analysis of the source prompt

1. **It combines several independent products.** Document extraction, hardware execution, lifecycle management, and MCP need separate acceptance criteria. One all-at-once plan would hide dependencies and partial failures.
2. **Privacy must cover every outbound payload.** Local document extraction alone is insufficient if retrieved text, embeddings, chat history, summaries, error bodies or tool outputs later reach a cloud model. The current agent already sends retrieved context to Claude.
3. **The schema examples conflict.** The prompt alternates vector dimensions 1536 and 1024; code uses 384. It alternates `limbo` and `dormant`, omits promised emails/project-environment relations in its sample DDL, and includes commented-out `CREATE TABLE` beginnings on comment lines. It uses `CREATE EXTENSION pgvector`, while the extension is named `vector` ([official pgvector documentation](https://github.com/pgvector/pgvector)). The samples are not executable acceptance criteria.
4. **Deployment versions disagree.** Prompt: PostgreSQL 16; Compose: 17; README: 18. Retain the current development baseline for the first slice. Verify the actual server before a later migration; do not infer it from documentation.
5. **Durable notes cannot depend on volatile STM.** Stage source revisions durably; only session state and disposable telemetry should be volatile. A restart must not lose an acknowledged import.
6. **Popularity is not importance.** Counting every retrieved candidate rewards already popular material. Start future lifecycle work with explicit opens/edits/pins, deduplicated events and manual restore; evaluate automatic decay before enabling it. Financial retention must not inherit note inactivity rules.
7. **Hardware state needs uncertainty.** A failed SSH connection does not establish powered-off state. Cache observation time, error and freshness; report unknown separately from offline. Sending a magic packet does not establish that a machine booted.
8. **Async is not a property of a label.** Wrapping blocking Paramiko calls in an async function does not establish nonblocking behavior. Choose one bounded execution strategy in the hardware spec; avoid adding both SSH libraries without a use case.
9. **MCP does not establish permission or privacy.** Exposing private search to a cloud-backed client can bypass backend routing. Future MCP needs explicit export policy and authenticated, restricted tools; “root administrator” is an unsafe default product requirement.
10. **A new framework stack is not necessary for the first outcome.** Keep Poetry, `src/second_brain`, psycopg, and the current vector model. Defer SQLAlchemy, Redis/Celery and the `app/` rewrite until a specific workload requires them.

## Alternatives considered

| Approach | Benefit | Cost / risk | Recommendation |
|---|---|---|---|
| Full Agentic OS rewrite | Broad feature coverage | Many untested boundaries, migration and operational risks | Defer |
| Reliable ingestion first | Prevents lost or stale notes | Existing chat still exports private retrieval | Next after privacy |
| Private chat routing first | Closes current privacy gap, enables local use | Does not solve ingestion durability or graph search | Select for first spec |

The riskiest product assumption is that local answer quality on available Proxmox resources is sufficient. Before expanding ingestion, evaluate a locally selected model on 20 representative Polish/English questions with known source notes; record grounded answers, incorrect claims and latency. A proposed go/no-go target is at least 16 correct, source-supported answers and no private cloud requests. This is an experiment target, not a measured result or claim about any model.

## Decomposition of the remaining vision

These are future specification boundaries, not requirements of the first plan.

1. **Durable notes:** source identity and revisions, initial scan plus reconciliation, durable jobs with retry/claim semantics, atomic replacement, tombstones, staged visibility and provenance. Exit: crash/retry/delete fixtures preserve the correct source version.
2. **Knowledge relations:** projects, skills with cycle prevention, source entities, project environments, versioned chunk/model identity, data-preserving migration. Exit: relational filters and source citations survive migration; embedding models are never mixed in one similarity space.
3. **Document intelligence:** separately specify git, PDF and email adapters. Preserve originals, extraction provenance and confidence; scanned PDFs report OCR-needed rather than empty success; attachments and mbox deduplication need explicit rules. Exit: fixture-based extraction and private processing verified.
4. **Consolidation and lifecycle:** idempotent revision promotion, scheduling, reference-event definition, pinning, limbo filtering and restore. Exit: interrupted runs retry safely; explicit limbo search finds archived material without silently restoring it.
5. **Hardware:** allowlisted diagnostic commands and nodes, host-key verification, credentials outside database rows, deadlines, bounded retries, capability checks, timestamped cache. Exit: fixtures distinguish online, unknown, stale and wake-requested states. Real WoL support must be measured per node.
6. **Omni-search:** compose retrieval and explicit hardware actions, with separate outcomes if either fails; hardware changes require explicit requested intent. Define HTTP authentication and network exposure before LAN deployment. Exit: the compound prompt has a traceable partial-success response.
7. **MCP server, then optional host:** expose the same application services with per-tool authorization and private export restrictions. Select transport and SDK against official documentation at implementation time. Exit: client integration tests exercise real services, not fabricated sample output.

Dependencies: privacy precedes document ingestion; durable notes precede consolidation; graph relations and hardware services precede combined search; MCP wraps stable services. Hardware discovery can be specified independently once its security boundary is defined.

## Design Critique: existing CLI and proposed assistant interaction

### Overall Impression

The CLI has a simple question/answer flow and source-aware retrieval. Its largest usability gap is that users cannot see where their information is sent or whether their source material is current. This critique is based on code, not a rendered screen or usability study.

### Usability

| Finding | Severity | Recommendation |
|---|---|---|
| Provider is invisible; personal context reaches Claude | Critical | Show Private/Ollama or Cloud/Anthropic before input; make cloud an explicit separate mode |
| Watcher prints success but has no freshness/error surface | Moderate | In the ingestion slice, expose source revision, last success and actionable failed state |
| “Thinking...” collapses retrieval and generation | Moderate | Name the active provider and offer actionable local-service errors |
| Citation numbers restart per turn and are model-generated | Moderate | Display a deterministic per-answer source list; distinguish retrieved evidence from generated prose |
| Prompt merges hardware action and search result | Critical for future hardware release | Show action state, observation timestamp and retrieval outcome separately |

### Visual Hierarchy

- Code emphasizes the readiness banner and “Brain” answer label. Provider/privacy mode should be equally visible before the first input.
- Intended reading flow: mode, question, progress, answer, sources or error recovery.
- Keep biological terms in documentation; use “Pending”, “Searchable”, and “Archived” in user-facing lifecycle controls.

### Consistency

| Element | Issue | Recommendation |
|---|---|---|
| Status vocabulary | Prompt mixes dormant/limbo; schema has ACTIVE/CONSOLIDATED for a different lifecycle | Separate ingestion state from archival state; choose one vocabulary in each future spec |
| Entry points | Packaged watcher and legacy root script differ | Document the packaged command as supported; retire legacy path in ingestion work |
| Configuration | Provider setting exists but agent ignores it | Validate provider/mode combinations and expose effective mode |

### Accessibility

- Color contrast: unverified; terminal theme determines rendered contrast. Green/cyan/yellow styling alone cannot establish a pass.
- Touch targets: not applicable to this CLI; no web UI exists to inspect.
- Text readability: terminal-controlled font size; preserve plain-text mode labels, wrapped source paths and keyboard operation. Never rely on color alone for privacy/error states.

### What Works Well

- One primary chat interaction with keyboard exit and cleanup.
- Retrieval already carries source identifiers and similarity information.
- Small embedder/retriever/database boundaries support incremental work.

### Priority Recommendations

1. Make private routing enforceable and visible, including history and failures.
2. Make note updates atomic and observable before increasing ingestion volume.
3. Define source-backed answers and truthful hardware states before adding a dashboard or compound executor.

## Spec Review of the original prompt

**Status:** Issues Found

**Issues:**
- [Scope]: independent ingestion, memory, hardware and protocol subsystems lack separate completion criteria; a single plan would be too broad.
- [Privacy]: no complete outbound-data policy or cloud-client boundary; local parsing alone can still leak source data.
- [Schema]: conflicting dimensions/statuses and missing promised relations prevent a coherent migration plan.
- [Lifecycle]: retry, source deletion, consolidation recovery and counting/decay rules are unspecified; implementations could lose data or hide relevant documents.
- [Hardware]: no definition of unknown/stale states or action permissions; errors could be reported as successful actions.

**Recommendations (advisory, do not block approval):**
- Retain the existing repository layout and evaluate local answer quality before selecting heavier infrastructure.
- Treat the linked first-slice spec as the planning candidate; the full vision still needs the later specs listed above.
