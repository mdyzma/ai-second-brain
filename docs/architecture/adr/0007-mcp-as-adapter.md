# ADR-0007: MCP server as a thin adapter with shareable-only default

**Status:** Proposed
**Date:** 2026-09-29
**Deciders:** Michal Dyzma

## Context

The prompt proposes an MCP server (so Claude Code / Claude Desktop can query memory, wake machines, inspect GPUs) and an MCP host, and frames Claude Code as "Root Administrator". MCP clients backed by cloud models forward tool results to the provider. Therefore any private memory returned by an MCP tool leaves the LAN — bypassing the `llm` gateway entirely.

## Decision

- Build the MCP server (official Python `mcp` SDK, stdio transport, phase 8) as a **thin adapter** over the same application services as the CLI — no duplicated logic, no simulated outputs.
- Treat every MCP caller as **cloud tier**: `search_memory` returns `shareable` sources only by default. `MCP_ALLOW_PRIVATE=true` is an explicit, documented operator opt-in with a startup warning.
- Tools are read-only by default (`search_memory`, `get_node_status`, `list_projects`, `add_note` into a dedicated `Inbox/` source). State-changing tools (`wake_node`) are opt-in per tool in config; destructive/free-form tools (arbitrary SSH) are never exposed.
- Defer the MCP **host** role; the CLI/agent does not need to consume third-party MCP servers for any current requirement.

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| **A. Adapter, shareable default (chosen)** | Keeps privacy promise; reuses services | Less useful until sources are marked shareable |
| B. Full-access MCP ("root administrator") | Maximum convenience | Silent private-data egress; remote-execution risk via prompt injection |
| C. No MCP | No risk | Loses interoperability the owner wants |

## Consequences

- Easier: Claude Code can use shareable engineering knowledge (ADRs, public repos) and node status safely.
- Harder: owner must classify folders/sources as shareable to get value — this is a feature, and the UI must make it easy.
- Revisit: a local-model MCP client (e.g. an Ollama-backed agent) could safely receive private results — allow per-client profiles then.

## Action Items
1. [ ] Add sensitivity classification (the web UI "Sources" screen: mark a folder or source shareable; `POST /api/sources/{id}/sensitivity`), shipped before MCP.
2. [ ] MCP integration tests against real services and a seeded DB, asserting no private content in tool output.
