import { infiniteQueryOptions, keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Filters, SourceRow } from "./types";

export class HttpError extends Error {
  constructor(readonly status: number) {
    super(`Request failed with status ${status}`);
  }
}

/** HTTP status of a failed query; 0 for network errors. */
export function statusOf(error: unknown): number {
  return error instanceof HttpError ? error.status : 0;
}

export const POLL_FAST_MS = 10_000;
export const POLL_SLOW_MS = 60_000;

type PollInput = {
  revisions: { pending: number };
  last_run: { trigger: string; finished_at: string | null } | null;
};

/** Shared refresh cadence for the summary and the list. */
export function pollInterval(data: PollInput | undefined, scanQueued: boolean): number {
  const scanning = data?.last_run?.trigger === "manual" && !data.last_run.finished_at;
  return scanQueued || scanning || (data?.revisions.pending ?? 0) > 0 ? POLL_FAST_MS : POLL_SLOW_MS;
}

export function rowsOf(data: { pages: { items: SourceRow[] }[] } | undefined): SourceRow[] {
  const seen = new Set<string>();
  const rows: SourceRow[] = [];
  for (const page of data?.pages ?? []) {
    for (const row of page.items) {
      if (seen.has(row.id)) continue;
      seen.add(row.id);
      rows.push(row);
    }
  }
  return rows;
}

export const sourcesKeys = {
  summary: ["sources", "summary"] as const,
  list: (f: Filters) => ["sources", "list", f] as const,
};

export const summaryQueryOptions = queryOptions({
  queryKey: sourcesKeys.summary,
  queryFn: async () => {
    const { data, response } = await api.GET("/api/sources/summary");
    if (!data) throw new HttpError(response.status);
    return data;
  },
  refetchInterval: (query) => pollInterval(query.state.data, false),
});

export function listQueryOptions(filters: Filters) {
  return infiniteQueryOptions({
    queryKey: sourcesKeys.list(filters),
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const query: { state?: NonNullable<Filters["state"]>; q?: string; cursor?: string } = {};
      if (filters.state) query.state = filters.state;
      if (filters.q) query.q = filters.q;
      if (pageParam) query.cursor = pageParam;
      const { data, response } = await api.GET("/api/sources", { params: { query } });
      if (!data) throw new HttpError(response.status);
      return data;
    },
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
  });
}

/** `detail` is the API's error code (e.g. "scan_already_queued"), never shown as-is. */
export type ActionResult =
  | { ok: true }
  | { ok: false; status: number; detail?: string | undefined };

/** The string error code in an API error body, if any. */
export function detailOf(body: unknown): string | undefined {
  if (typeof body !== "object" || body === null || !("detail" in body)) return undefined;
  return typeof body.detail === "string" ? body.detail : undefined;
}

async function post(
  call: () => Promise<{ response: Response; error?: unknown }>,
): Promise<ActionResult> {
  try {
    const { response, error } = await call();
    if (response.status === 202) return { ok: true };
    return { ok: false, status: response.status, detail: detailOf(error) };
  } catch {
    return { ok: false, status: 0 };
  }
}

export function retrySource(id: string): Promise<ActionResult> {
  return post(() =>
    api.POST("/api/sources/{source_id}/retry", { params: { path: { source_id: id } } }),
  );
}

export function reconcileVault(): Promise<ActionResult> {
  return post(() => api.POST("/api/sources/reconcile"));
}
