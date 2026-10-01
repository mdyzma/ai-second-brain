import { useQuery } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { facetsQueryOptions, SearchHttpError, searchQueryOptions } from "@/features/search/api";
import { clearRecent, recentQueries, rememberQuery } from "@/features/search/labels";
import { SearchScreen } from "@/features/search/SearchScreen";
import { parseSearch, toSearchParams } from "@/features/search/url";
import { statusOf } from "@/features/sources/api";

export const Route = createFileRoute("/_app/search")({
  validateSearch: (raw: Record<string, unknown>) => toSearchParams(parseSearch(raw)),
  component: SearchRoute,
});

function SearchRoute() {
  const state = parseSearch(Route.useSearch());
  const navigate = useNavigate({ from: Route.fullPath });
  const search = useQuery(searchQueryOptions(state));
  const facets = useQuery(facetsQueryOptions);
  const [recent, setRecent] = useState(recentQueries);
  useEffect(() => {
    if (search.data && state.q.trim()) {
      rememberQuery(state.q.trim());
      setRecent(recentQueries());
    }
  }, [search.data, state.q]);
  const error = search.error;
  return (
    <SearchScreen
      state={state}
      onState={(next) => void navigate({ search: toSearchParams(next), replace: true })}
      response={search.data}
      facets={facets.data}
      loading={search.isFetching}
      error={error ? statusOf(error) : undefined}
      errorDetail={error instanceof SearchHttpError ? error.detail : undefined}
      recent={recent}
      onClearRecent={() => {
        clearRecent();
        setRecent([]);
      }}
    />
  );
}
