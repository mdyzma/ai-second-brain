import { useInfiniteQuery } from "@tanstack/react-query";
import { createFileRoute, useLocation, useNavigate } from "@tanstack/react-router";
import { entitiesQuery } from "@/features/graph/api";
import { EntitiesScreen } from "@/features/graph/EntitiesScreen";
import { parseEntitiesSearch, toEntitiesParams } from "@/features/graph/entityUrl";
import { historyStep } from "@/features/search/url";
import { statusOf } from "@/features/sources/api";

export const Route = createFileRoute("/_app/entities/")({
  validateSearch: (raw: Record<string, unknown>) => toEntitiesParams(parseEntitiesSearch(raw)),
  component: EntitiesRoute,
});

function EntitiesRoute() {
  const state = parseEntitiesSearch(Route.useSearch());
  const navigate = useNavigate({ from: Route.fullPath });
  const isDraft = useLocation({ select: (l) => l.state.searchDraft === true });
  const list = useInfiniteQuery(entitiesQuery(state.type, state.q));
  return (
    <EntitiesScreen
      state={state}
      onState={(next, change) => {
        const step = historyStep(isDraft, change);
        void navigate({
          search: toEntitiesParams(next),
          replace: step.replace,
          state: { searchDraft: step.draft },
        });
      }}
      items={list.data?.pages.flatMap((p) => p.items) ?? []}
      loading={list.isPending}
      error={list.isError ? statusOf(list.error) : null}
      hasMore={list.hasNextPage}
      onLoadMore={() => void list.fetchNextPage()}
    />
  );
}
