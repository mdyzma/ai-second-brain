import { type QueryClient, queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { HttpError } from "@/features/sources/api";
import type { Digest } from "./types";

export const digestKeys = {
  all: ["digest"] as const,
  latest: ["digest", "latest"] as const,
  byRun: (id: string) => ["digest", "run", id] as const,
  runs: ["digest", "runs"] as const,
};

export const DIGEST_POLL_FAST_MS = 5_000;
export const DIGEST_POLL_SLOW_MS = 60_000;
const RUNS_LIMIT = 30;

/** Fast only while the shown run is still running. */
export function digestPollInterval(data: Pick<Digest, "run"> | undefined): number {
  return data?.run?.status === "running" ? DIGEST_POLL_FAST_MS : DIGEST_POLL_SLOW_MS;
}

/** The latest run's digest, or the digest of the run with id `runId`. */
export function digestQuery(runId?: string) {
  return queryOptions({
    queryKey: runId ? digestKeys.byRun(runId) : digestKeys.latest,
    refetchInterval: (query) => digestPollInterval(query.state.data),
    queryFn: async () => {
      const { data, response } = runId
        ? await api.GET("/api/digest/run/{run_id}", { params: { path: { run_id: runId } } })
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

/** Start a manual run; rejects with HttpError (409 while a run is open). A 409 means the
 * cached digest is stale (it showed no open run), so it is refreshed before rejecting. */
export async function startRun(queryClient: QueryClient) {
  const { data, response } = await api.POST("/api/nightly/run");
  if (!data) {
    if (response.status === 409) await queryClient.invalidateQueries({ queryKey: digestKeys.all });
    throw new HttpError(response.status);
  }
  await queryClient.invalidateQueries({ queryKey: digestKeys.all });
  return data;
}

export function useStartNightlyRun() {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: () => startRun(queryClient) });
}
