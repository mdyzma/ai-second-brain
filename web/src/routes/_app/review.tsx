import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { digestKeys } from "@/features/digest/api";
import {
  decideEntity,
  decideLinks,
  graphKeys,
  graphStatusQuery,
  reviewEntitiesQuery,
  reviewLinksQuery,
  runExtraction,
  searchEntities,
  useReviewAutoRefresh,
} from "@/features/graph/api";
import { loadErrorCopy } from "@/features/graph/labels";
import { ReviewScreen, type ReviewTab } from "@/features/graph/ReviewScreen";
import { statusOf } from "@/features/sources/api";

type ReviewSearch = { tab?: ReviewTab };

export const Route = createFileRoute("/_app/review")({
  validateSearch: (raw: Record<string, unknown>): ReviewSearch =>
    raw.tab === "links" ? { tab: "links" } : {},
  component: ReviewRoute,
});

function ReviewRoute() {
  const queryClient = useQueryClient();
  const { tab = "entities" } = Route.useSearch();
  const navigate = useNavigate({ from: Route.fullPath });
  const status = useQuery(graphStatusQuery);
  useReviewAutoRefresh(status.data);
  const entities = useInfiniteQuery(reviewEntitiesQuery);
  const links = useInfiniteQuery(reviewLinksQuery);
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: graphKeys.all }),
      queryClient.invalidateQueries({ queryKey: digestKeys.all }),
    ]);

  if (status.data === undefined) {
    if (status.isError)
      return (
        <p role="alert" className="text-sm text-danger-fg">
          {loadErrorCopy(statusOf(status.error))}
        </p>
      );
    return <p className="text-sm text-fg-muted">Loading…</p>;
  }
  return (
    <ReviewScreen
      tab={tab}
      onTab={(next) =>
        void navigate({ search: next === "links" ? { tab: next } : {}, replace: true })
      }
      status={status.data}
      entities={entities.data?.pages.flatMap((p) => p.items) ?? []}
      entitiesLoading={entities.isPending}
      entitiesError={entities.isError ? statusOf(entities.error) : null}
      hasMoreEntities={entities.hasNextPage}
      onLoadMoreEntities={() => void entities.fetchNextPage()}
      links={links.data?.pages.flatMap((p) => p.items) ?? []}
      linksLoading={links.isPending}
      linksError={links.isError ? statusOf(links.error) : null}
      hasMoreLinks={links.hasNextPage}
      onLoadMoreLinks={() => void links.fetchNextPage()}
      onDecide={async (id, body) => {
        const result = await decideEntity(id, body);
        if (result.ok) await refresh();
        return result;
      }}
      onDecideLinks={async (items) => {
        const result = await decideLinks(items);
        if (result.ok) await refresh();
        return result;
      }}
      onRun={async (scope) => {
        const result = await runExtraction(scope);
        if (result.ok) await queryClient.invalidateQueries({ queryKey: graphKeys.status });
        return result;
      }}
      onSearch={searchEntities}
    />
  );
}
