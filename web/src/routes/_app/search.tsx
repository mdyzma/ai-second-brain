import { useQuery } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { facetsQueryOptions, SearchHttpError, searchQueryOptions } from "@/features/search/api";
import { SearchScreen } from "@/features/search/SearchScreen";
import { parseSearch, toSearchParams } from "@/features/search/url";
import { useRememberQuery } from "@/features/search/useRememberQuery";
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
  const { recent, clear } = useRememberQuery(state.q, search);
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
      onClearRecent={clear}
    />
  );
}
