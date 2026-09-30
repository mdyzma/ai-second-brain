import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import {
  listQueryOptions,
  pollInterval,
  reconcileVault,
  retrySource,
  rowsOf,
  sourcesKeys,
  statusOf,
  summaryQueryOptions,
} from "@/features/sources/api";
import { refreshMessage, retryMessage, scanMessage } from "@/features/sources/labels";
import { SourcesScreen } from "@/features/sources/SourcesScreen";
import { useScanQueue } from "@/features/sources/scan";
import type { Filters } from "@/features/sources/types";

export const Route = createFileRoute("/_app/sources")({ component: SourcesRoute });

function SourcesRoute() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<Filters>({ state: null, q: "" });
  const [debounced, setDebounced] = useState(filters);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(filters), 300);
    return () => clearTimeout(t);
  }, [filters]);

  const [scanQueued, setScanQueued] = useState(false);
  const summary = useQuery({
    ...summaryQueryOptions,
    refetchInterval: (query) => pollInterval(query.state.data, scanQueued),
  });
  const lastRun = summary.data?.last_run ?? null;
  const scan = useScanQueue(lastRun);
  if (scan.queued !== scanQueued) setScanQueued(scan.queued);
  const list = useInfiniteQuery({
    ...listQueryOptions(debounced),
    refetchInterval: pollInterval(summary.data, scan.queued),
  });

  if (summary.data === undefined) {
    if (summary.isError)
      return (
        <p role="alert" className="text-sm text-danger-fg">
          Couldn't load sources.
        </p>
      );
    return <p className="text-sm text-fg-muted">Loading…</p>;
  }
  const serverScanning = lastRun?.trigger === "manual" && !lastRun.finished_at;
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["sources"] });
  return (
    <SourcesScreen
      summary={summary.data}
      rows={rowsOf(list.data)}
      hasMore={list.hasNextPage}
      scanPending={serverScanning || scan.queued}
      notice={notice ?? scan.notice}
      refreshNote={summary.isError ? refreshMessage(statusOf(summary.error)) : null}
      listError={list.isError}
      listLoading={list.isPending}
      loadingMore={list.isFetchingNextPage}
      onRetry={async (row) => {
        const result = await retrySource(row.id);
        setNotice(result.ok ? null : retryMessage(result.status));
        await refresh();
      }}
      onScan={async () => {
        const result = await reconcileVault();
        if (result.ok) {
          setNotice(null);
          scan.start();
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
