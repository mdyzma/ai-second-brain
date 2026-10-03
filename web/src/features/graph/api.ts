import {
  infiniteQueryOptions,
  type QueryClient,
  queryOptions,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "@/api/client";
import { detailOf, HttpError } from "@/features/sources/api";
import type {
  EntityDecision,
  EntitySummary,
  EntityType,
  ExtractScope,
  LinkDecision,
} from "./types";

export const graphKeys = {
  all: ["graph"] as const,
  status: ["graph", "status"] as const,
  entities: ["graph", "review-entities"] as const,
  links: ["graph", "review-links"] as const,
};

export const GRAPH_POLL_FAST_MS = 5_000;
export const GRAPH_POLL_SLOW_MS = 60_000;

type CountsInput = { revisions: { pending: number; extracted: number; failed: number } };

/** Fast only while extract jobs are waiting or running; never-extracted notes alone do not count. */
export function graphPollInterval(data: { queued: number } | undefined): number {
  return (data?.queued ?? 0) > 0 ? GRAPH_POLL_FAST_MS : GRAPH_POLL_SLOW_MS;
}

export function countsKey(data: CountsInput): string {
  const r = data.revisions;
  return `${r.pending}:${r.extracted}:${r.failed}`;
}

/** Refetch the review lists whenever extraction progress changes (not on first load). */
export function refreshOnProgress(
  queryClient: QueryClient,
  previous: string | null,
  data: CountsInput | undefined,
): string | null {
  if (!data) return previous;
  const key = countsKey(data);
  if (previous !== null && previous !== key) {
    void queryClient.invalidateQueries({ queryKey: graphKeys.entities });
    void queryClient.invalidateQueries({ queryKey: graphKeys.links });
  }
  return key;
}

export function useReviewAutoRefresh(data: CountsInput | undefined): void {
  const queryClient = useQueryClient();
  const last = useRef<string | null>(null);
  useEffect(() => {
    last.current = refreshOnProgress(queryClient, last.current, data);
  }, [queryClient, data]);
}

export const graphStatusQuery = queryOptions({
  queryKey: graphKeys.status,
  refetchInterval: (query) => graphPollInterval(query.state.data),
  queryFn: async () => {
    const { data, response } = await api.GET("/api/graph/status");
    if (!data) throw new HttpError(response.status);
    return data;
  },
});

export const reviewEntitiesQuery = infiniteQueryOptions({
  queryKey: graphKeys.entities,
  initialPageParam: undefined as string | undefined,
  queryFn: async ({ pageParam }) => {
    const { data, response } = await api.GET("/api/review/entities", {
      params: { query: pageParam ? { cursor: pageParam } : {} },
    });
    if (!data) throw new HttpError(response.status);
    return data;
  },
  getNextPageParam: (last) => last.next_cursor ?? undefined,
});

export const reviewLinksQuery = infiniteQueryOptions({
  queryKey: graphKeys.links,
  initialPageParam: undefined as string | undefined,
  queryFn: async ({ pageParam }) => {
    const { data, response } = await api.GET("/api/review/links", {
      params: { query: pageParam ? { cursor: pageParam } : {} },
    });
    if (!data) throw new HttpError(response.status);
    return data;
  },
  getNextPageParam: (last) => last.next_cursor ?? undefined,
});

export type Result = { ok: true } | { ok: false; status: number; detail?: string | undefined };
export type RunResult = { ok: true; queued: number } | Exclude<Result, { ok: true }>;

export async function decideEntity(id: string, body: EntityDecision): Promise<Result> {
  try {
    const { response, error } = await api.POST("/api/entities/{entity_id}/decide", {
      params: { path: { entity_id: id } },
      body,
    });
    if (response.status === 200) return { ok: true };
    return { ok: false, status: response.status, detail: detailOf(error) };
  } catch {
    return { ok: false, status: 0 };
  }
}

export async function decideLinks(items: LinkDecision[]): Promise<Result> {
  try {
    const { response, error } = await api.POST("/api/review/links", { body: { items } });
    if (response.status === 200) return { ok: true };
    return { ok: false, status: response.status, detail: detailOf(error) };
  } catch {
    return { ok: false, status: 0 };
  }
}

export async function runExtraction(scope: ExtractScope): Promise<RunResult> {
  try {
    const { data, response, error } = await api.POST("/api/graph/extract", { body: { scope } });
    if (response.status === 202 && data) return { ok: true, queued: data.queued };
    return { ok: false, status: response.status, detail: detailOf(error) };
  } catch {
    return { ok: false, status: 0 };
  }
}

/** Accepted entities for the merge and parent pickers; empty on any failure. */
export async function searchEntities(
  type: EntityType | undefined,
  q: string,
): Promise<EntitySummary[]> {
  try {
    const query: { type?: EntityType; q?: string } = {};
    if (type) query.type = type;
    if (q.trim()) query.q = q.trim();
    const { data } = await api.GET("/api/entities", { params: { query } });
    return data?.items ?? [];
  } catch {
    return [];
  }
}

export const entityKeys = {
  list: (type: EntityType | undefined, q: string) => ["graph", "entities", type ?? "", q] as const,
  detail: (id: string) => ["graph", "entity", id] as const,
};

/** Accepted entities for the Entities list, filtered by type and name. */
export function entitiesQuery(type: EntityType | undefined, q: string) {
  return infiniteQueryOptions({
    queryKey: entityKeys.list(type, q),
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) => {
      const query: { type?: EntityType; q?: string; cursor?: string } = {};
      if (type) query.type = type;
      if (q.trim()) query.q = q.trim();
      if (pageParam) query.cursor = pageParam;
      const { data, response } = await api.GET("/api/entities", { params: { query } });
      if (!data) throw new HttpError(response.status);
      return data;
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

export function entityQuery(id: string) {
  return queryOptions({
    queryKey: entityKeys.detail(id),
    retry: false,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/entities/{entity_id}", {
        params: { path: { entity_id: id } },
      });
      if (!data) throw new HttpError(response.status);
      return data;
    },
  });
}
