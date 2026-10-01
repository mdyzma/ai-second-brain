# ADR-0012: Salience as a bounded ranking prior, not a popularity filter

**Status:** Proposed. It supersedes the dormancy rules in the first draft of [system-design §4.3](../system-design.md#43-salience-and-dormancy).
**Date:** 2026-09-29
**Deciders:** Michal Dyzma

> **Status note (Phase 2b):** search ranks by reciprocal rank fusion of full text and vector similarity only. No salience prior is applied yet; it arrives with Phase 7, after the evaluation set described below exists.

## Context

The prompt's "synaptic plasticity + limbo" became, in the first draft: *score = Σ event weight × time decay; below a threshold → Dormant; Dormant excluded from default search.* The owner asked whether this promotes the most popular, most frequently mentioned material and lets one-time ideas be forgotten.

**It does.** Five mechanisms cause the bias:

| # | Mechanism | Effect |
|---|---|---|
| 1 | **Feedback loop (Matthew effect).** Only visible items get opened or cited, and being opened or cited raises the score that keeps them visible | Rich get richer; the ranking learns its own past output |
| 2 | **Absorbing state.** Dormant items are filtered out of default search, so they cannot earn the events that would revive them | Filtering is effectively deletion from everyday use |
| 3 | **Frequency ≠ value.** A one-off insight, a contact met once or a contract signed once is low-frequency *by nature* | The long tail, where a second brain beats your own memory, is exactly what decays |
| 4 | **System events counted as interest.** `search_hit` and `cited_in_answer` are produced by the system, not by the user | The score measures the retriever's attention, not the owner's |
| 5 | **Recency conflated with relevance.** Seasonal (annual taxes), paused projects and old decisions that still hold all look "cold" | A resumed project comes back without its context, which defeats the `resume` feature |

There is also a mechanism the metaphor hides: in the brain, a memory is revived by a **cue** (something associated with it appears), not by repetition. The first draft modelled only repetition.

## What dormancy is actually for

The legitimate problem is **stale-but-similar noise**: an old version of a plan outranking the current one, a superseded decision, an expired contract answering "what's my current hosting provider?". That is a **staleness** problem. Popularity is a poor proxy for it, and direct evidence for staleness exists:

- **Supersession:** a newer revision, a note that says "replaces X", an ADR marked superseded, or a near-duplicate with a newer date on the same entity.
- **Closure:** a project marked closed, a contract past `expiry_date`, an invoice paid.
- **Explicit user action:** archive, "let fade".

## Decision

### 1. Relevance dominates; salience is a small, bounded prior

```
final = rrf_relevance × (1 + prior),      prior ∈ [−0.15, +0.15]
prior = + user_interest     (0 … +0.10, decayed, user-originated signals only)
        + distinctiveness   (0 … +0.05, see 3)
        − staleness         (0 … −0.15, evidence-based, see 2)
```

A strongly matching item always ranks by its match. Salience only breaks ties between comparably relevant results. The bounds are proposed starting values, tuned with the evaluation below.

### 2. Tiers are driven by evidence, not popularity

| Tier | Set by | Search behavior |
|---|---|---|
| **Active** | default | normal |
| **Dormant** | no user activity for N months (computed) | **still searched**; no penalty by itself; eligible for resurfacing (4) |
| **Superseded** | evidence: newer revision/replacement, closed project, expired contract | searched with a staleness penalty; labeled "Superseded by …" with a link to the successor |
| **Archived** | user action only | excluded by default; `include archived` toggle |
| **Pinned** (flag) | user | never penalized |

Only the user removes something from default search. Nothing is hidden automatically.

### 3. Protect the long tail on purpose: distinctiveness

Measure each source's **distinctiveness** at consolidation time: 1 − the mean cosine similarity to its k = 5 nearest neighbours in other sources.

- A **one-off idea with no near neighbours** has high distinctiveness and gets a small bonus. It is unique, and losing it is losing information.
- A **cluster of near-duplicates** (ten notes restating the same thing) has low distinctiveness. That is where consolidation acts: it *proposes a merge* or marks the older duplicates Superseded. It never discards the unique item.

Rarity becomes a reason to keep something, not to forget it.

### 4. Revive by association (cue-based recall)

- **During consolidation:** for each new revision, look up its nearest *Dormant* sources above a similarity threshold. If there is a match, propose a link and add a digest item: "Related to an idea from March 2024: *…*". The old idea wakes because something new resembles it, not because it was popular.
- **At query time:** reserve 1 of the top-k result slots for the best-matching Dormant item above a relevance floor, shown as "From earlier". This is deliberate exploration that breaks the feedback loop (mechanism 1).
- **Rediscover cadence (owner decision: hybrid):**
  - *Daily, triggered only:* at most **1** item in the morning digest, and only when yesterday's activity (edits, captures, touched entities) matches a Dormant source above a high similarity threshold. Most days show nothing. This catches the association while the context is fresh.
  - *Weekly review (Sunday):* **3–5** dormant, highly distinctive items related to the week's projects/entities, each with *keep (pin)*, *let fade*, *merge into…* and *link to…*. This is deliberate, batched reflection.
  - An item shown in the daily slot is not repeated in the same week's review. An item dismissed ("let fade") is not resurfaced for 6 months unless a new strong association appears.
  - This is spaced, association-driven resurfacing, not random nostalgia.

### 5. Count only user-originated signals

| Signal | Counts? | Weight (proposed) |
|---|---|---|
| Edit, create | yes | 5 |
| Open a source (from UI or vault) | yes | 2 |
| Click a cited source / 👍 on a source | yes | 2 |
| Pin | yes (flag) | — |
| Commit, email or invoice *linked to the entity* | yes, to the entity, not to every chunk | 3 |
| Appeared in search results | **no** | 0 |
| Cited in a generated answer without interaction | **no** | 0 |
| 👎 "not relevant" on a source | negative, per query context only | — |

System-produced exposure never raises a score. That removes mechanism 4 and most of mechanism 1.

### 6. Different lifecycles for different kinds

| Kind | Rule |
|---|---|
| Ideas / notes | Dormant after 6 months without user activity. Never auto-superseded without evidence. Eligible for Rediscover |
| Projects | Follow explicit project status (active / paused / closed), not activity |
| Financial / legal | `retention='legal'`: never dormant; Superseded only by contract expiry or replacement |
| Emails | Thread-level. Dormant by age, but a new message in the thread revives the thread |
| Chat transcripts | Dormant quickly (30 days) unless something extracted from them is pinned or linked |

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| A. First draft: frequency × decay, dormant filtered | Simple; matches the prompt | All five biases above; silent loss of unique ideas |
| **B. Bounded prior + evidence-based staleness + distinctiveness + cue-based revival (chosen)** | Long tail protected; stale noise handled by real evidence; feedback loop broken | More moving parts; needs tuning and an evaluation set |
| C. No salience at all (pure relevance) | No bias, simplest | Stale plans and expired facts compete with current ones; no Rediscover feature |
| D. Learned ranker (click model) | Adapts to behavior | Too little data for one user; still exposed to feedback-loop bias |

Option C is the **baseline to beat**. Salience ships only if it improves the metrics below without hurting long-tail recall.

## Evaluation (prevents repeating the mistake)

Add to the retrieval eval set ([ADR-0006](0006-embedding-spaces.md)):

- **Long-tail queries (≥ 30 %):** targets are single-mention notes older than 6 months with no user activity.
- **Currency queries:** "current X" questions where a superseded source exists.

Metrics, compared with Option C:

| Metric | Guardrail / target |
|---|---|
| Recall@10 on long-tail queries | **must not drop** (hard guardrail) |
| Currency accuracy (the current source ranks above the superseded one) | must improve |
| Exposure share of bottom-50 % activity sources in the top-10 over a month | must not fall below the pure-relevance baseline |
| Rediscover acceptance (link accepted, or item opened/pinned), **tracked separately for daily and weekly** | ≥ 20 % after one month per trigger. Below that: daily → raise the similarity threshold; weekly → reduce to 3 items or move to biweekly |

## Consequences

- Easier: stale answers are addressed with explicit evidence the user can see ("Superseded by …"). One-off ideas stay findable and are actively resurfaced.
- Harder: consolidation computes nearest neighbours per new revision (cheap with HNSW) and distinctiveness (a nightly batch). Several parameters need tuning.
- UI: new states `Superseded` (with a link to the successor) and `From earlier` / `Rediscover` presentation. The Dormant badge becomes informational, not a warning.
- The prompt's biological metaphor is kept where it helps (cue-based reconsolidation) and dropped where it hurts (involuntary forgetting).

## Action Items
1. [ ] Update the schema: add `superseded` to `salience_tier`; add `superseded_by uuid`, a `distinctiveness real` column in `salience_scores`, and a `kind_policy` table.
2. [ ] Remove `search_hit` and uninteracted `cited_in_answer` from the salience events.
3. [ ] Build the long-tail and currency queries into the eval set before enabling any prior.
4. [ ] Ship in order: evidence-based Superseded → Rediscover digest section → reserved "From earlier" slot → user-interest prior.
