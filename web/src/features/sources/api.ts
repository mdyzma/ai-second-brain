import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Filters } from "./types";

export const sourcesKeys = {
  summary: ["sources", "summary"] as const,
  list: (f: Filters) => ["sources", "list", f] as const,
};

export const summaryQueryOptions = queryOptions({
  queryKey: sourcesKeys.summary,
  queryFn: async () => {
    const { data, response } = await api.GET("/api/sources/summary");
    if (!data) throw new Error(`Sources summary failed with status ${response.status}`);
    return data;
  },
  refetchInterval: (query) => {
    const data = query.state.data;
    const scanning = data?.last_run?.trigger === "manual" && !data.last_run.finished_at;
    return data && (data.revisions.pending > 0 || scanning) ? 10_000 : 60_000;
  },
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
      if (!data) throw new Error(`Sources list failed with status ${response.status}`);
      return data;
    },
    getNextPageParam: (last) => last.next_cursor,
  });
}

export type ActionResult = { ok: true } | { ok: false; status: number };

async function post(call: () => Promise<{ response: Response }>): Promise<ActionResult> {
  try {
    const { response } = await call();
    return response.status === 202 ? { ok: true } : { ok: false, status: response.status };
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
