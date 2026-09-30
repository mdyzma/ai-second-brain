# Phase 1b: follow-up backlog

Date: 2026-09-30. Source: the task reviews and the final whole-branch review of Phase 1b (private chat). Every item below was **triaged as "later"**: none blocks Phase 1b.

These items were fixed before release and are not listed:
- the busy-check race and the timing-dependent 409 test;
- the Anthropic base URL, now pinned so environment variables can't redirect it;
- the README privacy wording;
- escaping of untrusted evidence;
- remote images in answers;
- `[n]` citations inside code;
- the delete flow;
- the Stop e2e assertion;
- the README screenshot.

The final review also confirmed that a client disconnect closes the upstream Ollama stream immediately.

## Watch in CI

- **Cold-start flake:** seen once locally in `auth.spec.ts` ("wrong password": Password label not found within 30 s).
- **Linux teardown** of the `pnpm exec tsx` fake-Ollama process (port 11501) is unverified until the first CI run.

## Behaviour worth improving

- **Provider errors:**
  - Ollama's 4xx "context" classification matches the raw body, not the JSON `error` field. A model name containing "context" is misreported as `context_too_long`.
  - No `num_ctx` is sent, so Ollama silently truncates long prompts and `context_too_long` rarely fires.
- **Anthropic:** a mid-stream SSE `overloaded_error` arriving on HTTP 200 maps to `provider_error`, not `cloud_rate_limited`.
- **Unexpected exceptions** (not `ChatError`):
  - they log `outcome=interrupted` and end the SSE stream with no final `error` event;
  - rejected `turn_in_progress` attempts are not logged.
- **Cancellation:** `run_turn` doesn't wrap `provider.stream` in `contextlib.aclosing`. This is harmless in the SSE path (verified), but it's the tidier contract.
- **Lifespan:** `app.py` builds the HTTP client and services before its `try`, so a failed startup leaks the client and the pool.
- **Ollama status:** `status()` has no single-flight on an expired cache and returns the cached (mutable) list.
- **Web, error handling:**
  - 401, 403 and 5xx all show "Can't reach the server."
  - `toTurnEvent` checks only the event name, not the payload shape.
  - `useTurn` resets its controller outside `try/finally`.
- **Web, UX:**
  - The sessions list shows "No conversations yet." while loading or on error.
  - Loading and error states of `/ask/$sessionId` have no back link on mobile.
  - The first send waits for a sessions refetch before navigating.
- **Web, composer:**
  - Over the limit, the only signals are colour and a disabled Send button. The counter uses the untrimmed text.
  - Focus return is a no-op while the composer is disabled.
  - Safari's IME Enter (`keyCode` 229) isn't handled.
- **Accessibility:**
  - `aria-live` on the whole streaming answer can be chatty.
  - A `role="alert"` is nested inside the live region.
  - The disabled cloud option's reason isn't linked with `aria-describedby`.
  - `SourceList` has an `h3` with no `h2` context.
- **Links in answers:** external http(s) links open on one click. Once retrieval exists, consider showing the destination host next to them, because injected notes could build leaking URLs.
- **Minor data edges:**
  - `recent_turns(limit=0)` differs between the in-memory and Postgres repositories.
  - `updated_at` can move backwards on out-of-order saves.
  - The URL validator accepts a non-numeric port.
  - `httpx2.InvalidURL` isn't caught in `stream()`. Config validation prevents it.

## Tests and tooling (housekeeping)

- **Config:** no test that a bad `SB_OLLAMA_ENDPOINTS` names the variable, and nothing pins `info.version == API_VERSION` beyond `api-client-check`.
- **Repository:** no concurrent `save_turn`, rollback or `heading=None` round-trip tests.
- **Events:** the event-schema `required` test covers 3 of 6 models. `ErrorEvent.code` and `component` are plain `str`, so TypeScript loses the literal unions.
- **Providers:** missing cases for select stopping after the first success, a 5xx body containing "context", status with a closed port, Anthropic connect/header timeouts, a dropped stream, and `ChatError` having no `__cause__`.
- **Fakes:** `ServerThread.start()` failure leaks its socket and thread. The e2e fake's `JSON.parse` has no try/catch, and port 11501 is duplicated in the spec and the config.
- **Service:** no test that the session stays busy after a rejected second turn, for the `degraded` flag in status and receipt, for a history storage error, or for a consumer that stops after the receipt.
- **API:** there's no integration test for a mid-turn disconnect; the unit tests, e2e Stop and the final-review probe cover it. The `db` and `make_chat_client` fixtures are duplicated across two test files.
- **Egress tests:**
  - no direct "retriever never called" assertion;
  - the redirect test doesn't check the origin request, the private suffix or that no turn was saved.
- **CLI:**
  - `chat-smoke`'s invalid-settings path is untested;
  - failures go to stdout;
  - `_chat_smoke(settings: Any)`;
  - one assertion is loose.
- **Web tests:**
  - multi-line `data`, mid-stream abort, `signal` passed to fetch, and an error event ending the stream;
  - composer focus, IME, the 7000 boundary, over-limit, and `TurnView`;
  - reference-style images;
  - NewSession double-submit.
- **Web structure:** `disabledReasonFor` lives in `NewSession`; move it to a shared module. The alert-dialog overlay has no z-index.
- **E2E:** sources-before-answer is checked only as final DOM order. The badge assertion uses `.first()`. The delete test doesn't reload to confirm persistence.
- **README:**
  - the roadmap's 1b row mentions "settings" (still a placeholder) and has no version yet;
  - "Errors are always `{detail}`" doesn't cover streamed turns;
  - the troubleshooting line should say "Ollama's `GET /api/version`";
  - the local-model steps should mention single quotes for `SB_OLLAMA_ENDPOINTS`;
  - the settings table still calls `SB_ANTHROPIC_BASE_URL` "Tests only".
