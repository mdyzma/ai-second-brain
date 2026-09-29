# ADR-0005: Local inference topology — GPU workstation on demand, CPU fallback on Proxmox

**Status:** Proposed (blocked on Phase 0 measurements)
**Date:** 2026-09-29
**Deciders:** Michal Dyzma

## Context

Privacy requires private content to be processed locally. The prompt places Ollama "inside Proxmox". The Proxmox node is assumed to have no GPU; the RTX 5090 workstation is powerful but not always on; the MacBook M1 is portable. Local answer quality is the riskiest assumption in the project.

## Decision

Treat "local" as *any owner machine on the trusted LAN*, configured as an ordered list of Ollama endpoints with a label each:

1. **Workstation (RTX 5090)** — preferred for interactive private chat when online, and for the nightly sleep cycle (the system wakes it via WoL, runs the batch, then suspends it if it woke it).
2. **Proxmox CPU LXC** — always-on fallback with a small quantized model; the UI labels it ("Private — small local model").
3. **MacBook** — optional, manual selection only.

The gateway never falls back to the cloud tier. Embeddings run on the Proxmox worker CPU.

## Options Considered

### Option A: On-demand GPU + CPU fallback (chosen)
**Pros:** best quality when it matters; the nightly batch justifies waking the GPU; always some private answer. **Cons:** two model sizes → answer quality varies; WoL/suspend reliability per node must be measured.

### Option B: CPU-only Ollama in Proxmox (prompt)
**Pros:** simplest; always on. **Cons:** 7–8 B CPU models may fail the bilingual eval and are slow for batch extraction over hundreds of thousands of chunks.

### Option C: Keep the workstation always on
**Pros:** simple, fast. **Cons:** power cost/noise of a 5090 box idling 24/7.

### Option D: GPU passthrough to Proxmox
**Pros:** single always-on inference host. **Cons:** requires a GPU in the Proxmox node — hardware purchase; revisit if Phase 0 shows CPU is inadequate.

## Trade-off Analysis

Option A converts the prompt's hardware orchestration from a demo into a real dependency of the memory system — which is a good reason to build it, but also means WoL failures degrade consolidation. Mitigation: sleep cycle defers or uses the CPU host and reports this in the morning digest.

## Consequences

- Easier: large-model extraction quality at night without 24/7 power draw.
- Harder: endpoint selection logic and labelling; model-specific prompt tuning for two models.
- Revisit: after Phase 0 — if the CPU model passes the eval, Option B may be enough for chat.

## Action Items
1. [ ] Phase 0: run the 20-question PL/EN eval on both hosts; record grounded-answer count and latency.
2. [ ] Measure WoL success rate and time-to-SSH for the workstation (10 trials).
3. [ ] Verify Proxmox hardware (GPU presence, RAM available for an LXC).
