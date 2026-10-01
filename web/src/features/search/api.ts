import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "@/api/client";
import { detailOf, HttpError } from "@/features/sources/api";
import type { SearchState } from "./url";

export class SearchHttpError extends HttpError {
  constructor(
    status: number,
    readonly detail?: string,
  ) {
    super(status);
  }
}

export function searchQueryOptions(state: SearchState) {
  return queryOptions({
    queryKey: ["search", state] as const,
    enabled: state.q.trim().length >= 2,
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const query: { q: string; folder?: string; tag?: string[] } = { q: state.q };
      if (state.folder) query.folder = state.folder;
      if (state.tags.length) query.tag = state.tags;
      const { data, error, response } = await api.GET("/api/search", { params: { query } });
      if (!data) throw new SearchHttpError(response.status, detailOf(error));
      return data;
    },
  });
}

export const facetsQueryOptions = queryOptions({
  queryKey: ["search", "facets"] as const,
  staleTime: 60_000,
  queryFn: async () => {
    const { data, response } = await api.GET("/api/search/facets");
    if (!data) throw new HttpError(response.status);
    return data;
  },
});
