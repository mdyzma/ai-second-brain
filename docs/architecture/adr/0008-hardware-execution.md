# ADR-0008: asyncssh with an allowlisted command catalog for hardware actions

**Status:** Proposed
**Date:** 2026-09-29
**Deciders:** Michal Dyzma

## Context

The prompt lists both Paramiko and AsyncSSH and describes wrapping Paramiko in async code. Paramiko is blocking; wrapping it in `async def` does not make it non-blocking. Hardware actions are triggered from chat, where LLM output and retrieved notes are untrusted (prompt injection could request commands).

## Decision

- Use **asyncssh** only (native asyncio, supports OpenSSH config aliases and `known_hosts`). Do not add Paramiko.
- Execute only named commands from a code-defined catalog keyed by node capability, with typed parameters and a parser each. No free-form command strings from any interface or model.
- Host keys must match `known_hosts`; no auto-accept. Keys stay in the worker user's `~/.ssh`, never in the DB.
- Deadlines: 5 s connect, 15 s command; one retry on connect error. Results always written as a timestamped observation.
- WoL via the `wakeonlan` package from the Proxmox-hosted worker on the same L2 segment; outcome recorded as `waking` until an SSH probe succeeds.
- Proxmox via `proxmoxer` with an API token bound to a read-only role.

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| **A. asyncssh + catalog (chosen)** | Non-blocking; safe by construction | Each new diagnostic needs code |
| B. Paramiko in a thread pool | Mature | Blocking model, threads; same safety work needed |
| C. Shell out to `ssh` via `asyncio.create_subprocess_exec` | Uses exact OpenSSH config | Process-per-call; parsing stderr for errors |
| D. Free-form commands with LLM choosing | Flexible | Remote code execution via prompt injection — rejected |

Option C is an acceptable fallback if asyncssh config compatibility causes friction with existing aliases.

## Consequences

- Easier: truthful, testable states (fake SSH server in tests).
- Harder: adding a command requires a PR — intentional.
- Revisit: Proxmox write actions (start/stop VM) need their own ADR with confirmation UX.

## Action Items
1. [ ] Inventory nodes: alias, MAC, broadcast address, capabilities; confirm WoL is enabled in BIOS/NIC of the workstation.
2. [ ] Fixture tests for online / unreachable / waking / stale.
