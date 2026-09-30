import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import {
  listQueryOptions,
  reconcileVault,
  retrySource,
  sourcesKeys,
  summaryQueryOptions,
} from "@/features/sources/api";
import { retryMessage, scanMessage } from "@/features/sources/labels";
import { SourcesScreen } from "@/features/sources/SourcesScreen";
import type { Filters } from "@/features/sources/types";

export const Route = createFileRoute("/_app/sources")({ component: SourcesRoute });

function SourcesRoute() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<Filters>({ state: null, q: "" });
  const [debounced, setDebounced] = useState(filters);
  // started_at of the last run when a scan was queued; the scan is done once a newer run finishes.
  const [queuedAfter, setQueuedAfter] = useState<string | null | undefined>(undefined);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(filters), 300);
    return () => clearTimeout(t);
  }, [filters]);
  const summary = useQuery(summaryQueryOptions);
  const list = useInfiniteQuery(listQueryOptions(debounced));
  const lastRun = summary.data?.last_run ?? null;
  const serverScanning = lastRun?.trigger === "manual" && !lastRun.finished_at;
  const finishedNewRun =
    lastRun !== null && lastRun.finished_at !== null && lastRun.started_at !== queuedAfter;
  useEffect(() => {
    if (queuedAfter !== undefined && finishedNewRun) setQueuedAfter(undefined);
  }, [queuedAfter, finishedNewRun]);

  if (summary.isPending) return <p className="text-sm text-fg-muted">Loading…</p>;
  if (summary.isError)
    return (
      <p role="alert" className="text-sm text-danger-fg">
        Couldn't load sources.
      </p>
    );
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["sources"] });
  return (
    <SourcesScreen
      summary={summary.data}
      rows={list.data?.pages.flatMap((p) => p.items) ?? []}
      hasMore={list.hasNextPage}
      scanPending={serverScanning || (queuedAfter !== undefined && !finishedNewRun)}
      notice={notice}
      listError={list.isError}
      onRetry={async (row) => {
        const result = await retrySource(row.id);
        setNotice(result.ok ? null : retryMessage(result.status));
        await refresh();
      }}
      onScan={async () => {
        const result = await reconcileVault();
        if (result.ok) {
          setNotice(null);
          setQueuedAfter(lastRun?.started_at ?? null);
        } else {
          setNotice(scanMessage(result.status));
        }
        await queryClient.invalidateQueries({ queryKey: sourcesKeys.summary });
      }}
      onFilter={setFilters}
      onLoadMore={() => void list.fetchNextPage()}
    />
  );
}
