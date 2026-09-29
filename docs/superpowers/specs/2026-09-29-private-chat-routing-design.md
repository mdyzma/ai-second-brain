# Private chat routing: first implementation specification

> **Revision (2026-09-29):** §3 (CLI user contract) and §5 (component layout) are superseded by the [Phase 1b spec](2026-09-29-phase-1b-private-chat-design.md), which implements these rules behind the web API. §4, §6 and §8 still apply.

Date: 2026-09-29. Status: proposed design for human review. Scope: one CLI chat routing boundary. Companion: [project assessment and roadmap](2026-09-29-second-brain-assessment.md).

## 1. Purpose and success

Enable the owner to ask questions about existing local notes without sending the question, retrieved text, source paths, history or generated answers to a cloud model. Preserve an explicitly selected cloud mode for generic development conversations. This implements the prompt's privacy constraint as a first slice; it does not claim delivery of the whole Agentic OS.

Assumptions proposed for this slice: one trusted local OS user; existing PostgreSQL and embedding model; an operator-managed Ollama endpoint within the trusted local deployment. All stored memories are private because existing rows lack reviewed export classifications. No cloud classification heuristic is permitted.

Success: private chat can retrieve existing notes and produce local answers; simulated provider failures produce zero cloud calls; explicit cloud chat never reads local memory; failed turns do not pollute conversation history.

## 2. Scope and choice

Choose two isolated session modes over per-document routing. Per-document routing would need classification, mixed-context rules and historical taint tracking that the database does not support. Local-only chat would be simpler but would remove the requested generic cloud workflow.

Included: provider abstraction, local Ollama adapter, existing Anthropic adapter, immutable session mode, safe configuration, CLI mode/source visibility, deterministic tests and operator instructions.

Excluded: schema changes, classification editor, cloud RAG, automatic provider choice, model downloads, new embedding model, note ingestion fixes, persistent chat, sleep/limbo, hardware, FastAPI, MCP and a graphical interface. The current ingestion data-loss issue is separately recorded in the assessment and remains a limitation.

## 3. User contract

- `second-brain chat` starts **Private — Ollama; local memory enabled**.
- `second-brain chat --mode private` is equivalent.
- `second-brain chat --mode cloud` starts **Cloud — Anthropic; messages sent to cloud; local memory disabled**. This explicit mode selection is the user's decision to send what they type. No semantic classifier promises to detect manually pasted private text.
- No mode changes within a running session. Exit and start a new command to change modes; histories are never transferred.
- Existing `quit`, `exit`, `q`, Ctrl-C and EOF exit behavior remains. `stats` retains its database-only behavior.
- Private responses display a deterministic “Retrieved sources” list with source number and source_file, falling back to category then memory UUID. It reflects the current turn, not proof that the model cited every source correctly. An empty retrieval says “No matching local sources”; the model may answer generally but must not claim local evidence.
- Error messages identify the failing component and an operator action without echoing prompts, response bodies, credentials or note text. A failed generation leaves the input loop usable.

## 4. Privacy and session rules

| Mode | Retrieval | Generation | History | Failure behavior |
|---|---|---|---|---|
| Private (default) | Existing local embedder and DB | Configured local Ollama only | In-process private messages | Report error; no cloud fallback |
| Cloud (explicit) | Never invoked; DB/embedder not constructed | Anthropic only | In-process cloud messages | Report error; no provider fallback |

Treat retrieved text as untrusted evidence. System instructions tell the model not to treat source text as commands. This slice exposes no tools to either provider. Model output cannot change mode, destination, or trigger execution.

Use mode-specific system instructions: private mode describes supplied local evidence and citations; cloud mode describes a general assistant and explicitly has no access to local memories. Do not reuse the existing memory-access claim in cloud mode.

Never log source content, user messages, provider bodies or history. Log only mode, component, duration and error category. Private routing is an application boundary, not protection against an operator deliberately pointing a “local” endpoint at an external service. Configuration documentation must state that trust assumption. Restrict the local client to the configured HTTP(S) origin, disable redirects and ambient proxy use, and never use hosted Ollama/model identifiers. Endpoint/model setup is manual; no automatic pulls or cloud fallback.

## 5. Components and data flow

Preserve `src/second_brain`, Poetry and synchronous CLI execution. No event loop or queue is needed.

- `core/agent.py`: orchestrates one mode, holds successful history, assembles evidence, invokes the injected provider. It no longer creates an Anthropic client unconditionally.
- A small provider module/package defines `generate(system: str, messages: list[Message]) -> str`, implements Ollama and Anthropic, and normalizes transport/response errors to a content-free application error.
- `main.py`: validates mode, wires only required dependencies, shows mode and per-turn retrieved sources, handles errors and cleanup.
- `config/settings.py`: validates selected mode's configuration before connecting any resources. Unused provider credentials are not required.
- Existing retriever and DB remain the private retrieval path. Cloud mode receives no retriever. No migration or data rewrite occurs.

Private turn: validate input → retrieve locally → build current context and temporary message list → generate locally → commit user/assistant pair to history → display answer and sources. Cloud turn skips retrieval and context assembly. A failed retrieval/generation appends neither message; retry is a new user action, with no automatic resend. Store only successful pairs; cap history at the latest 10 complete pairs. Retain the existing augmented private messages within that cap; all are local-only. Do not summarize overflow through another service. Provider context-limit errors are reported without fallback. This slice does not promise token-exact context budgeting across arbitrary local models: Ollama may truncate context according to its model/runtime configuration. Document that limitation explicitly; require the operator smoke check to use short fixtures within the installed model's context window. Token budgeting and long-document answer quality are deferred, rather than represented as a privacy guarantee.

Keep the current `Agent.chat(...) -> str` contract if useful for callers; expose current successful turn's source records separately and clear them before every attempt so failed turns cannot show stale citations. Provider protocol details may be adapted without changing these behavior requirements.

## 6. Provider and configuration contract

- CLI mode controls routing. The default is always private. Existing `LLM_PROVIDER` must not silently select cloud: an explicitly supplied value inconsistent with the mode is a startup configuration error. Valid matching values are `ollama` for private and `anthropic` for cloud. Remove the current implicit `anthropic` provider default.
- Private requires `LOCAL_OLLAMA_URL` and `LOCAL_LLM_MODEL`, both explicit nonempty values; URL must be HTTP(S), contain no userinfo/query/fragment, and identify the trusted endpoint. Do not infer a model from the old Claude model setting.
- Cloud uses existing `ANTHROPIC_API_KEY`, `LLM_MODEL`, and `LLM_MAX_TOKENS`. Do not require a database password, embedding model, or local endpoint in this mode. Model availability is checked by the provider response, not assumed from the existing default model name.
- Both adapters use one request per turn, 5-second connect timeout and 120-second read timeout, with SDK/client automatic retries disabled. These are proposed operational defaults, not measured latency guarantees.
- Ollama uses `POST /api/chat`, `stream: false`, system plus message history, the configured model and an output limit derived from `LLM_MAX_TOKENS`. Accept only a successful completed response with nonempty assistant text; reject malformed, incomplete or empty results. [Official Ollama API documentation](https://github.com/ollama/ollama/blob/main/docs/api.md) documents the chat endpoint and nonstreaming option.
- Anthropic gathers returned text blocks in order; a response with no text is an error. Neither adapter interprets generated tool requests as executable actions.
- Keep the 384-dimensional local embedding model unchanged. Provision its weights locally before private operation; the private acceptance test must run without model downloads. Local inference is distinct from initial dependency/model installation.
- Document environment export and `.env` behavior consistently for nested settings, including mode conflict examples. Verify actual loading with temporary-file tests rather than relying on nested BaseSettings defaults.

## 7. Compatibility and rollout

Default chat changes from Claude to private. Existing operators must configure the local endpoint/model or explicitly select cloud. Missing local configuration is a clear startup error, never a reason to fall back to Claude. Update README and `.env.example` with that intentional behavior change.

No database migration, PostgreSQL upgrade, embedding reindex or note rewrite is needed. Compose's current PostgreSQL 17 remains the development baseline for this slice; the deployed version is unverified. Preserve existing notes and UUIDs. If reverting code, warn in the operator instructions that the previous chat implementation sends retrieved notes to Claude; do not advertise reverting as a privacy-preserving fallback.

## 8. Acceptance and validation

Tests must observe outbound destinations and payloads, not merely assert a router decision.

1. Default private startup with a local fake HTTP endpoint and fake DB/embedder emits a local request containing the question and expected retrieved evidence; no Anthropic client is constructed or called.
2. Missing local config, connection failure, timeout, redirect, malformed JSON, empty text, incomplete response and provider-reported context-limit errors produce actionable errors and zero cloud requests. Verify redirects/proxies cannot reroute private data.
3. Explicit cloud mode works with invalid/unavailable DB and embedding settings because those resources are not initialized. Its payload contains only system instructions and user/cloud conversation messages; no local source records.
4. A private session followed by a separately created cloud session shares no messages or sources. Source prompt-injection text cannot switch mode or instantiate tools.
5. Failed calls leave the successful history unchanged and clear displayed source state. More than 10 successful pairs retain the newest 10 whole pairs.
6. Source lists are deterministic for successful private turns; empty retrieval is explicit. Cloud has no local source list. Plain text labels convey all privacy/error information without color.
7. Configuration tests cover exported environment and temporary `.env` files, matching/mismatched provider values, mode-specific required fields, and URL rejection. Captured logs contain no seeded secret or private fixture text.
8. Existing agent tests are adapted to inject providers; retriever/settings tests retain relevant behavior. Run the repository lint/test commands. Real embedding tests may require pre-provisioned weights; report unavailable prerequisites rather than claiming a pass.
9. Operator smoke check uses an installed local model and disposable local fixture data to obtain a source-backed private answer with outbound cloud access blocked. This deployment check can remain explicitly unexecuted until local infrastructure is supplied; it is required before claiming the deployment works.

This is ready for a single implementation plan once the document review passes and the human accepts the proposed scope. Local model choice and endpoint values are deployment configuration, not missing product behavior. Broader roadmap units require their own specifications.
