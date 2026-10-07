import { type QueryClient, queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { HttpError } from "@/features/sources/api";
import type { Digest } from "./types";

export const digestKeys = {
  all: ["digest"] as const,
  latest: ["digest", "latest"] as const,
  byDate: (d: string) => ["digest", d] as const,
  runs: ["digest", "runs"] as const,
};

export const DIGEST_POLL_FAST_MS = 5_000;
export const DIGEST_POLL_SLOW_MS = 60_000;
const RUNS_LIMIT = 30;

/** Fast only while the shown run is still running. */
export function digestPollInterval(data: Pick<Digest, "run"> | undefined): number {
  return data?.run?.status === "running" ? DIGEST_POLL_FAST_MS : DIGEST_POLL_SLOW_MS;
}

/** The latest run's digest, or the latest run on `date` (YYYY-MM-DD). */
export function digestQuery(date?: string) {
  return queryOptions({
    queryKey: date ? digestKeys.byDate(date) : digestKeys.latest,
    refetchInterval: (query) => digestPollInterval(query.state.data),
    queryFn: async () => {
      const { data, response } = date
        ? await api.GET("/api/digest/{run_date}", { params: { path: { run_date: date } } })
        : await api.GET("/api/digest");
      if (!data) throw new HttpError(response.status);
      return data;
    },
  });
}

export const nightlyRunsQuery = queryOptions({
  queryKey: digestKeys.runs,
  queryFn: async () => {
    const { data, response } = await api.GET("/api/nightly/runs", {
      params: { query: { limit: RUNS_LIMIT } },
    });
    if (!data) throw new HttpError(response.status);
    return data;
  },
});

/** Start a manual run; rejects with HttpError (409 while a run is open). */
export async function startRun(queryClient: QueryClient) {
  const { data, response } = await api.POST("/api/nightly/run");
  if (!data) throw new HttpError(response.status);
  await queryClient.invalidateQueries({ queryKey: digestKeys.all });
  return data;
}

export function useStartNightlyRun() {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: () => startRun(queryClient) });
}
