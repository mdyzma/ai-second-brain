export type SearchState = { q: string; folder?: string; tags: string[] };

export function parseSearch(params: Record<string, unknown>): SearchState {
  const q = typeof params.q === "string" ? params.q : "";
  const folder = typeof params.folder === "string" && params.folder ? params.folder : undefined;
  const raw = params.tag;
  const tags = (Array.isArray(raw) ? raw : raw === undefined ? [] : [raw]).filter(
    (t): t is string => typeof t === "string" && t.length > 0,
  );
  return folder ? { q, folder, tags } : { q, tags };
}

/** "typing" is a debounced keystroke update; "commit" is Enter, a filter change or a recent click. */
export type SearchChange = "typing" | "commit";

/**
 * How a search change moves browser history. Typing creates one "draft" entry and then keeps
 * replacing it, so prefixes never pile up; the next commit settles the draft in place. Any other
 * change pushes, so Back and Forward step between searches.
 */
export function historyStep(
  currentIsDraft: boolean,
  change: SearchChange,
): { replace: boolean; draft: boolean } {
  return { replace: currentIsDraft, draft: change === "typing" };
}

export function toSearchParams(state: SearchState): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (state.q) out.q = state.q;
  if (state.folder) out.folder = state.folder;
  if (state.tags.length) out.tag = state.tags;
  return out;
}
