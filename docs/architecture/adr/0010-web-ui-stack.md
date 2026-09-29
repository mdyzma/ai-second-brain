# ADR-0010: Web UI stack — React + TypeScript SPA (Vite), built by Node, served statically

**Status:** Proposed
**Date:** 2026-09-29
**Deciders:** Michal Dyzma

## Context

The owner chose Node + React as the main UI. The UI needs: streaming chat (SSE), search with filters, the resume/digest pages, a review queue, node status that refreshes live, and source and sharing management. It serves one user on the LAN, with no SEO and no public traffic. Privacy: the page must never load third-party resources.

## Decision

| Concern | Choice | Why | Rejected |
|---|---|---|---|
| Language | **TypeScript (strict)** | Typed API client, refactor safety, discriminated unions for SSE events and node states | Plain JS: loses the generated-contract benefit |
| Framework | **React 19** | Owner choice | — |
| Build/dev | **Vite** SPA | Fast, simple, static output; nothing needs a server runtime | **Next.js**: SSR/RSC and a Node server add runtime surface with no benefit for a LAN single-user app. **Remix/React Router framework mode**: same reasoning |
| Routing | **TanStack Router** | Type-safe routes and search params (filters in the URL) | React Router: fine, weaker typing of search params |
| Server state | **TanStack Query** + `openapi-fetch` on generated types | Caching, refetch for node status, mutations | Redux/RTK Query: more boilerplate |
| Streaming | `fetch` + SSE parser (`eventsource-parser`) | POST-initiated streams, which native `EventSource` cannot do | WebSockets: bidirectional not needed |
| Styling | **Tailwind CSS v4** with CSS-variable tokens (`@theme`) | Tokens as the single source; dark mode | CSS-in-JS: runtime cost |
| Components | **shadcn/ui** (Radix primitives, copied into repo) | Accessible primitives you own; no vendor lock | MUI/Mantine: heavy theming layers |
| Markdown answers | `react-markdown` + `rehype-sanitize` | Model output is untrusted: sanitize, no raw HTML | `dangerouslySetInnerHTML`: rejected |
| Forms/validation | React Hook Form + Zod (for client-only forms) | Types line up with the generated client | — |
| Lint/format | **Biome** | One fast tool; fewer configs | ESLint + Prettier: acceptable alternative if plugin needs appear |
| Tests | **Vitest** + Testing Library, **Playwright** e2e against the dev stack | Standard | Jest: slower with Vite |
| Package manager | **pnpm** (Node 22/24 LTS, pinned via `packageManager` + `.nvmrc`) | Fast, strict | npm: fine; yarn: no need |
| Fonts/icons | Self-hosted (Inter/variable font files in repo), `lucide-react` | No external requests (CSP `default-src 'self'`) | Google Fonts CDN: third-party request |

## Consequences

- Node is needed only in dev and CI (`just web-build`). Production serves `web/dist` from Caddy.
- The generated client (`web/src/api/`) is committed and verified in CI. Hand-edits are forbidden.
- Revisit: if a mobile capture app is wanted, use a PWA on the same SPA first, and consider React Native only after that.

## Action Items
1. [ ] Scaffold `web/` with the above; add `just web-dev`, `just web-check`, `just api-client`.
2. [ ] Implement tokens and primitives from [design-system-audit.md](../design-system-audit.md) before the first feature screen.
