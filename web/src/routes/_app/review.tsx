import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import {
  decideEntity,
  decideLinks,
  graphKeys,
  graphStatusQuery,
  reviewEntitiesQuery,
  reviewLinksQuery,
  runExtraction,
  searchEntities,
} from "@/features/graph/api";
import { loadErrorCopy } from "@/features/graph/labels";
import { ReviewScreen } from "@/features/graph/ReviewScreen";
import { statusOf } from "@/features/sources/api";

export const Route = createFileRoute("/_app/review")({ component: ReviewRoute });

function ReviewRoute() {
  const queryClient = useQueryClient();
  const status = useQuery(graphStatusQuery);
  const entities = useInfiniteQuery(reviewEntitiesQuery);
  const links = useInfiniteQuery(reviewLinksQuery);
  const refresh = () => queryClient.invalidateQueries({ queryKey: graphKeys.all });

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
