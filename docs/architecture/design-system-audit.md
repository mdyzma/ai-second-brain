# Design system: audit and foundation spec (React web UI)

Date: 2026-09-29. **Scope change:** the web UI (React + TypeScript + Tailwind v4 + shadcn/ui, [ADR-0010](adr/0010-web-ui-stack.md)) is now the primary interface, and the MVP CLI is discarded. No UI code exists yet, so there are no components to score. This document therefore does two things:

1. **Audits what the design system inherits**: the vocabulary and state models in the prompt, the specs and the database design. These leak into the UI first, and they are inconsistent.
2. **Specifies the foundation** (tokens, primitives, domain components, accessibility bar) so the first feature screen is built on it rather than beside it.

## 1. Audit summary

**Existing components:** 0 · **Inherited vocabulary issues:** 8 · **Readiness score:** 20/100 (a vocabulary and state model is partly defined in the system design; there are no tokens, components or docs yet)

### Naming consistency (inherited)

| Issue | Where | Standard to adopt |
|---|---|---|
| `limbo` / `dormant` / `decayed` / `cold-storage` for one tier | Prompt | **Dormant** (UI), `salience_tier.dormant` (code). It means *quiet, still searchable*, not hidden ([ADR-0012](adr/0012-salience-without-popularity-bias.md)) |
| Ingestion progress and relevance share `status`/`active` | Prompt, old V1 schema | Two vocabularies: **Pending / Searchable / Failed** and **Active / Dormant / Superseded / Archived** |
| STM / LTM / engram / hippocampus / cortex / synapse | Prompt | Docs and module names only. The UI says Inbox, Memory, Digest, Dormant, Links |
| "Brain:" as the answer author | Old CLI | Label the **tier**, not a persona: `Answer · Private (workstation)` |
| "offline" when SSH fails | Prompt | **Online / Waking / Unreachable / Unknown**, plus a "Stale" modifier on any observation older than its TTL |
| "Omni-search" | Prompt | **Ask** (chat with generation) vs **Search** (sources only). Two different promises |
| "Sleep cycle" | Prompt | **Nightly consolidation** in settings; the user-facing output is the **Digest** |
| "Reference count" | Prompt | Not shown. The UI shows *Last used* and the **Pinned** state; scores stay internal |

### State model coverage

| Domain | States defined (system design) | Token | Component |
|---|---|---|---|
| Privacy tier | ✅ private / cloud / withheld | ❌ | ❌ |
| Ingestion | ✅ pending / searchable / failed / tombstoned | ❌ | ❌ |
| Salience | ✅ active / dormant / superseded / archived + pinned | ❌ | ❌ |
| Node | ✅ online / waking / unreachable / unknown + stale | ❌ | ❌ |
| Link review | ✅ proposed / accepted / rejected | ❌ | ❌ |
| Stream | ⚠️ implied by SSE events | ❌ | ❌ |

## 2. Tokens

All tokens are CSS custom properties in `web/src/design-system/tokens.css`, exposed to Tailwind v4 through `@theme`. There are light and dark values (`prefers-color-scheme` plus a manual toggle via `[data-theme]`). **Components use semantic tokens only**, never raw palette values. A Biome/CI grep forbids hex values and arbitrary Tailwind colors (`bg-[#…]`) outside `tokens.css`.

### 2.1 Layers

```
palette   --gray-50…950, --green-…, --violet-…, --amber-…, --red-…, --cyan-…   (raw, OKLCH)
semantic  --color-bg, --color-surface, --color-surface-raised, --color-border,
          --color-text, --color-text-muted, --color-accent, --color-focus-ring,
          --color-danger, --color-warning, --color-success
domain    --tier-private-*, --tier-cloud-*, --ingest-*, --salience-*, --node-*, --link-*
```

### 2.2 Domain state tokens

Every state = **label + icon + color**. Color is never the only carrier (WCAG 1.4.1).

| Token group | State | Label | Icon (lucide) | Color role |
|---|---|---|---|---|
| `tier` | private | Private | `shield-check` | green |
| | cloud | Cloud | `cloud` | violet |
| | withheld | Withheld (private) | `eye-off` | amber |
| `ingest` | pending | Pending | `loader` (static when reduced motion) | muted |
| | searchable | Searchable | `check-circle` | green |
| | failed | Failed | `alert-triangle` | red |
| `salience` | active | (no badge) | — | default |
| | dormant | Dormant (informational, still searched) | `moon` | muted |
| | superseded | Superseded by … (links to successor) | `replace` | amber-muted |
| | from-earlier | From earlier (resurfaced dormant hit) | `history` | accent-muted |
| | archived | Archived | `archive` | muted |
| | pinned | Pinned | `pin` | amber |
| `node` | online | Online | `circle-dot` | green |
| | waking | Waking | `sunrise` | cyan |
| | unreachable | Unreachable | `circle-off` | red |
| | unknown | Unknown | `help-circle` | muted |
| | stale (modifier) | "seen 14 min ago" | `clock` | muted |
| `link` | proposed | Proposed | `git-pull-request` | amber |
| | accepted | Linked | `link` | green |
| | rejected | Rejected | `unlink` | muted |

Each color role defines `-fg`, `-bg` and `-border` for both themes. Every `-fg`/`-bg` pair must reach **4.5:1** contrast and the icons/borders **3:1**, checked automatically (below).

### 2.3 Other scales

- **Type:** self-hosted Inter variable (UI) + JetBrains Mono (paths, hashes, NIP, command output). Scale: 12 / 14 / 16 (body) / 18 / 20 / 24 / 30. Line height 1.5 for body, 1.25 for headings.
- **Spacing:** the Tailwind 4 px base; component padding uses only 2 / 3 / 4 / 6.
- **Radius:** `--radius-sm 4px`, `--radius 8px`, `--radius-lg 12px`.
- **Elevation:** 3 levels (surface, raised, overlay).
- **Motion:** `--duration-fast 120ms`, `--duration 200ms`; every animation respects `prefers-reduced-motion`. Streaming text never animates per token beyond appending.

## 3. Components

### 3.1 Primitives (shadcn/ui, copied into `design-system/ui/`)

Button, Input, Textarea, Select, Checkbox, Switch, Dialog, AlertDialog (confirmations), DropdownMenu, Popover, Tooltip, Tabs, Toast (Sonner), Badge, Card, Table, Skeleton, ScrollArea, Command (⌘K palette). These are restyled only through tokens.

### 3.2 Domain components (the product's real design system)

| Component | Purpose | Key states / variants | Notes |
|---|---|---|---|
| `TierBadge` | Shows where the conversation goes | private · cloud · private-degraded ("small local model") | Always visible in the chat header and on each answer |
| `ModeSwitcher` | Choose the tier for a **new** session | private (default) · cloud | Switching starts a new session; confirmation copy explains that history does not carry over |
| `ChatComposer` | Input with slash commands (`/wake`, `/search`) | idle · streaming (Stop) · disabled (no local model) | Enter sends, Shift+Enter adds a newline; label names the tier |
| `AnswerBlock` | Sanitized Markdown answer | streaming · done · interrupted · error | Citations `[1]` link to `SourceList` items |
| `SourceList` / `SourceCard` | Deterministic evidence, rendered **before** the answer | searchable · dormant · superseded · from-earlier · withheld summary · empty | Path in mono, heading path, score, open/pin actions |
| `ActionReceipt` | Result of a hardware action | sent · waking · online · failed · timed-out | Never merged into answer prose; shows observed time |
| `NodeCard` | Hardware status | online · waking · unreachable · unknown · stale | GPU/VRAM meters with numeric text (not bars alone); Wake needs `AlertDialog` confirmation |
| `IngestStatus` | Freshness of a source | pending · searchable · failed (retry) | Used in the Sources table and after capture |
| `SalienceControl` | Pin / archive / restore / 👍👎 on a source | active · dormant · superseded · archived · pinned | Only explicit user actions change salience; exposure never does |
| `LinkReviewItem` | Accept or reject a proposed link | proposed · accepted · rejected | Shows evidence snippet + confidence; keyboard `A`/`R` |
| `DigestSection` | Morning digest blocks | new · needs review · rediscover (daily single / weekly batch) · newly superseded · failures · deadlines | Each item deep-links to its screen |
| `ResumePanel` | Project resume page sections | loading (skeleton per section) · partial (one source failed) | Sections fail independently |
| `SystemBanner` | Global degraded state | DB down · no local model · worker backlog | Every private-tier failure ends with "Nothing was sent to the cloud." |
| `CaptureBox` | Quick note to Inbox | idle · saving · pending · searchable | Global shortcut `C` |

Each domain component gets a short doc page (purpose, props, states, a11y, do/don't) next to its code, and a Vitest render test per state. Adding **Storybook** or **Ladle** is optional. It is worth it once there are more than 10 domain components; until then a `/dev/components` route listing all states is enough.

### 3.3 Screens (information architecture)

`Ask` (chat) · `Search` · `Projects` → `Resume` · `Digest` · `Review` · `Nodes` · `Sources` (ingestion state, sensitivity, salience) · `Settings` (models, hosts, schedules, login).

Navigation is a left sidebar on desktop and a bottom bar on narrow screens (the MacBook is also used as a mobile-ish device). The ⌘K palette reaches every screen and action.

## 4. Accessibility bar (WCAG 2.1 AA)

- Contrast checked in CI: a small script parses `tokens.css` and asserts the pair ratios in both themes. Playwright + `@axe-core/playwright` runs on every screen.
- Keyboard: every action is reachable; visible focus ring (`--color-focus-ring`, 3:1); dialogs trap focus; `Esc` closes.
- Streaming answers sit in an `aria-live="polite"` region that announces the completed answer, not every token. The Stop button is always focusable while streaming.
- Status never relies on color alone (label + icon). Icons that carry meaning have `aria-label`s.
- Targets are at least 24×24 px (2.5.8); 44 px for primary touch actions.
- `prefers-reduced-motion` and `prefers-color-scheme` are honored.

## 5. Priority actions

1. **Write `tokens.css` + the contrast check before any screen.** It is cheap now and expensive to retrofit.
2. **Build `TierBadge`, `SourceList`, `AnswerBlock`, `SystemBanner` and `ChatComposer` in Phase 1b.** They carry the privacy promise visually.
3. **Model component props on generated API types** (`components['schemas']['SourceRef']`, `ActionResult`, `NodeState`), so UI states can never drift from backend states.
4. **Enforce the vocabulary:** a lint list of forbidden user-facing words (`limbo`, `engram`, `synapse`, `offline` for nodes) checked over `web/src`.
