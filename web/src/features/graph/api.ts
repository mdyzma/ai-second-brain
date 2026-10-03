import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
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

export const graphStatusQuery = queryOptions({
  queryKey: graphKeys.status,
  refetchInterval: 30_000,
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
