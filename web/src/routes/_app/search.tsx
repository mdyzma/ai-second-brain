import { useQuery } from "@tanstack/react-query";
import { createFileRoute, useLocation, useNavigate } from "@tanstack/react-router";
import { facetsQueryOptions, SearchHttpError, searchQueryOptions } from "@/features/search/api";
import { SearchScreen } from "@/features/search/SearchScreen";
import { historyStep, parseSearch, toSearchParams } from "@/features/search/url";
import { useRememberQuery } from "@/features/search/useRememberQuery";
import { statusOf } from "@/features/sources/api";

declare module "@tanstack/react-router" {
  interface HistoryState {
    /** This history entry was made by debounced typing; the next search change replaces it. */
    searchDraft?: boolean;
  }
}

export const Route = createFileRoute("/_app/search")({
  validateSearch: (raw: Record<string, unknown>) => toSearchParams(parseSearch(raw)),
  component: SearchRoute,
});

function SearchRoute() {
  const state = parseSearch(Route.useSearch());
  const navigate = useNavigate({ from: Route.fullPath });
  const isDraft = useLocation({ select: (l) => l.state.searchDraft === true });
  const search = useQuery(searchQueryOptions(state));
  const facets = useQuery(facetsQueryOptions);
  const { recent, clear, remember } = useRememberQuery(state.q, search);
  const error = search.error;
  return (
    <SearchScreen
      state={state}
      onState={(next, change) => {
        const step = historyStep(isDraft, change);
        void navigate({
          search: toSearchParams(next),
          replace: step.replace,
          state: { searchDraft: step.draft },
        });
      }}
      onRemember={remember}
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
