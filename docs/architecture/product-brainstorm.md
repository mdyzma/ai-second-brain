# Product brainstorm: what is this second brain *for*?

Date: 2026-09-29. Format: captured brainstorm (frame → diverge → provoke → converge). Opinions are deliberate; they are inputs to decisions, not decisions. Open questions for the owner are at the end.

## 1. Frame

**Who has the problem?** One person: an engineer with a home lab, bilingual notes, commercial and personal projects, invoices and contracts, and several machines.

**What do they do today?** Obsidian search, grep, email search, remembering which box has the GPU, asking a cloud chatbot and pasting context in by hand (leaking private context in the process).

**Why now?** Phase 1 (LTM + CLI) works, and the current chat sends private notes to Claude — the gap that motivated the routing spec.

**Constraint that shapes everything:** private data stays on the LAN.

### Jobs to be done

1. *When I start work on a project I haven't touched in months,* I want to recover its context (decisions, open threads, where it runs) *so I can be productive in minutes, not an afternoon.*
2. *When I need a fact buried in paperwork* (NIP, contract end date, invoice amount), I want an exact answer with the document *so I don't dig through PDFs and email.*
3. *When I capture a half-formed idea,* I want it connected to what I already know *so ideas compound instead of rotting in an inbox.*
4. *When I want to run something heavy,* I want to know which machine is free and have it ready *so I don't walk to the PC or SSH around.*
5. *When I use AI tools for coding,* I want them to know my conventions and past decisions *without handing them my private life.*

Job 1 and 3 are the emotional core ("I don't lose my own thinking"). Job 2 is the most measurable. Job 4 is the most fun and the least valuable per unit of effort.

## 2. Diverge — ideas beyond the prompt

### Idea 1: The morning digest is the product
Instead of a chat-first UI, the primary surface is a daily note written into the Obsidian vault: "Yesterday you captured 7 notes; 3 linked to *LLM fine-tune*; 1 contract expires in 30 days; 2 old ideas relate to what you worked on this week — rediscover?" Chat becomes the drill-down.
*Why interesting:* meets the user where they already are (Obsidian), and turns the invisible sleep cycle into something felt.

### Idea 2: "Resume project" command
`second-brain resume <project>` → last decisions (ADRs), last commits, open TODOs from notes, related emails, which machine it runs on and its current state, offer to wake it. This is JTBD #1 as one command and exercises every subsystem.

### Idea 3: The nightly shift
The sleep cycle wakes the RTX 5090, runs big-model consolidation, then suspends it. Hardware orchestration stops being a demo and becomes the reason consolidation quality is high. (Adopted into [ADR-0005](adr/0005-local-inference-topology.md).)

### Idea 4: Forgetting as a conversation, not a threshold
Nothing goes dormant silently. The digest proposes: "These 5 ideas haven't been touched in 6 months." Buttons/commands: *keep (pin)*, *let fade*, *merge into X*. The decay score only nominates; the human decides — at least until the system has earned trust.

*Update after review:* frequency-based decay has a popularity bias and buries one-off ideas. [ADR-0012](adr/0012-salience-without-popularity-bias.md) replaces it with evidence-based staleness, a distinctiveness bonus, and **Rediscover**, which resurfaces old ideas related to current work. Forgetting becomes rediscovery.

### Idea 5: Deadline radar from paperwork
Contracts' expiry dates and invoices' due dates → a calendar feed (local ICS file served on LAN) and digest warnings. Small, concrete, obviously useful — and a natural acceptance test for PDF extraction accuracy.

### Idea 6: Engineering persona for cloud tools (the *safe* MCP)
From git history + ADRs, generate a reviewed "engineering conventions" document (commit style, preferred libraries, architecture habits) marked **shareable**, exposed via MCP to Claude Code. Cloud AI gets your style, never your notes.

### Idea 7: Remove something — no chat UI at all at first
Ship ingestion + digest + `resume` + search results (sources only, no generation). If retrieval is good, generation is a bonus; if retrieval is bad, generation hides it. This isolates the riskiest variable.

### Idea 8: Inversion — how would we make this second brain useless?
Ingest everything, answer confidently without sources, silently hide old stuff, send data to the cloud, need babysitting. Reversed: **ingest selectively, always cite, forget only with consent, local by default, self-report failures.** These are the product principles.

### Idea 9: Capture from anywhere
`second-brain note "…"` from any terminal, a share-sheet shortcut on the Mac, an email alias to an IMAP folder → all land as `Inbox/` sources. Capture friction, not retrieval, is what kills most second brains.

### Idea 10: Ask the brain about the brain
"What did I learn about pgvector this year?" as a *timeline* view (entity → sources by date). The graph earns its keep when it answers time-shaped questions that plain vector search can't.

## 3. Provoke

- **Strongest argument against the whole thing:** Obsidian + a good local search plugin + a cloud chatbot with carefully pasted snippets gets 70% of the value for 5% of the effort. The project must beat that on *privacy* and *cross-source linking* (notes ↔ email ↔ invoices ↔ git ↔ machines), or it's a hobby.
- **The biomimetic framing is a trap if it drives requirements.** Brains forget involuntarily; a tool that forgets involuntarily is broken. Use the metaphor for *prioritization of attention*, never for *loss of data*.
- **The riskiest assumption** is that a local model gives answers good enough to prefer over a cloud one. If Phase 0 fails, the product shifts toward Idea 7 (retrieval-first, generation optional) — that's still valuable.
- **Second riskiest:** that the user will keep feeding it. Capture paths (Idea 9) and the digest (Idea 1) matter more than a fourth ingestion adapter.
- **Scope smell:** email + PDFs + git + hardware + MCP + graph + decay is seven products. The owner will be tempted to build the fun ones (hardware, MCP) first. Resist until the core loop (capture → searchable → cited answer → digest) works end to end.

## 4. Converge

| Idea | User impact | Effort | Evidence | Verdict |
|---|---|---|---|---|
| 2. `resume <project>` | High (JTBD 1) | Medium | Strong (self-reported pain) | **North-star feature** for phases 4–8 |
| 1. Morning digest | High | Low–Medium | Plausible | **Do** with sleep cycle (phase 4) |
| 4. Consent-based forgetting | Medium, protects trust | Low | Strong (design principle) | **Do** — replaces automatic limbo in phase 7 |
| 5. Deadline radar | Medium, concrete | Low after PDF extraction | Strong | **Do** as phase-6 acceptance feature |
| 7. Retrieval-first | Hedge | Low | Depends on Phase 0 | **Keep ready** as fallback |
| 9. Capture anywhere | High for adoption | Low | Plausible | **Do** `note` CLI early (phase 2) |
| 6. Shareable persona via MCP | Medium | Medium | Plausible | Phase 8 |
| 3. Nightly shift | Medium | Medium | — | Adopted in ADR-0005 |
| 10. Timeline view | Medium | Low once graph exists | Weak | Later |

**Top 3 to pursue, with the cheapest test for each:**

1. **`resume <project>`** — Test: hand-assemble a resume page for one real project from existing notes/git in 30 minutes; if the owner would use it weekly, build it.
2. **Morning digest in the vault** — Test: after phase 2, generate a digest with only ingestion stats + "notes without links" for 2 weeks; measure how often it's opened.
3. **Local answer quality (Phase 0)** — Test: 20-question eval on both local hosts; decides between chat-first and retrieval-first.

**Product principles (from Idea 8):** local by default · always cite · forget only with consent · report own failures · capture must be effortless.

## 5. Set aside (interesting, not now)

- MCP *host* role (the brain calling third-party MCP servers).
- Proxmox write actions (start/stop VMs from chat).
- Multi-user / family sharing.
- Voice capture and transcription.
- Automatic sensitivity classification (explicitly rejected for privacy reasons; manual folder-level marking instead).

## 6. Open questions for the owner

1. Which job matters most to you personally — **resume a project (1)** or **paperwork facts (2)**? This decides whether phase 4 (graph) or phase 6 (documents) comes first after durable notes.
2. Is the Obsidian vault the source of truth for new thoughts, or should the brain accept captures that are *not* in the vault (CLI/email notes)? If yes, should it write them back into the vault?
3. Would you accept the workstation being woken every night (noise/power), or only on demand?
4. Which folders/repos could be marked **shareable** today? Without any, cloud mode and MCP stay memory-less.
5. Does the Proxmox node have a GPU or spare RAM for a 14–32 B CPU model? (Unblocks ADR-0005.)
