import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { cn } from "@/design-system/cn";
import { Button } from "@/design-system/ui/button";
import { badgeFor, bannersFor, relativeTime, type Tone } from "./labels";
import type { Filters, SourceRow, SourcesSummary, StateFilter } from "./types";

const TONES: Record<Tone, string> = {
  pending: "border-ingest-pending-border bg-ingest-pending-bg text-ingest-pending-fg",
  searchable: "border-ingest-searchable-border bg-ingest-searchable-bg text-ingest-searchable-fg",
  failed: "border-ingest-failed-border bg-ingest-failed-bg text-ingest-failed-fg",
  neutral: "border-border bg-surface text-fg-muted",
};
const FILTERS: { label: string; value: StateFilter }[] = [
  { label: "All", value: null },
  { label: "Waiting", value: "pending" },
  { label: "Searchable", value: "indexed" },
  { label: "Failed", value: "failed" },
  { label: "Deleted", value: "deleted" },
];

type Props = {
  summary: SourcesSummary;
  rows: SourceRow[];
  hasMore: boolean;
  scanPending: boolean;
  onRetry: (row: SourceRow) => Promise<void>;
  onScan: () => Promise<void>;
  onFilter: (filters: Filters) => void;
  onLoadMore: () => void;
  notice?: string | null;
  listError?: boolean;
};

function Card({
  title,
  value,
  detail,
}: {
  title: string;
  value: string;
  detail?: string | undefined;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-4">
      <p className="text-sm text-fg-muted">{title}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {detail ? <p className="mt-1 text-xs text-fg-muted">{detail}</p> : null}
    </div>
  );
}

function canRetry(row: SourceRow): boolean {
  return row.state === "failed" || (row.state === "indexed" && row.embedded < row.chunks);
}

export function SourcesScreen({
  summary,
  rows,
  hasMore,
  scanPending,
  onRetry,
  onScan,
  onFilter,
  onLoadMore,
  notice = null,
  listError = false,
}: Props) {
  const [filters, setFilters] = useState<Filters>({ state: null, q: "" });
  const { embedded, total } = summary.embedding;
  const pct = total === 0 ? 100 : Math.floor((embedded / total) * 100);
  const run = summary.last_run;
  const update = (next: Filters) => {
    setFilters(next);
    onFilter(next);
  };
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Sources</h1>
        <Button onClick={() => void onScan()} disabled={scanPending || !summary.vault.configured}>
          <RefreshCw aria-hidden /> {scanPending ? "Scan queued…" : "Scan now"}
        </Button>
      </div>
      {notice ? (
        <p
          role="alert"
          className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg"
        >
          {notice}
        </p>
      ) : null}
      {bannersFor(summary).map((text) => (
        <p
          key={text}
          role="status"
          className="rounded-md border border-warning-border bg-warning-bg px-3 py-2 text-sm text-warning-fg"
        >
          {text}
        </p>
      ))}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Card title="Indexed" value={String(summary.revisions.indexed)} />
        <Card title="Waiting" value={String(summary.revisions.pending)} />
        <Card title="Failed" value={String(summary.revisions.failed)} />
        <Card
          title={`Embedded ${pct}%`}
          value={`${pct}%`}
          detail={`${embedded} of ${total} chunks`}
        />
        <Card
          title="Last scan"
          value={run ? relativeTime(run.started_at) : "never"}
          detail={run ? `${run.counts.changed ?? 0} changed` : undefined}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <Button
            key={f.label}
            size="sm"
            variant={filters.state === f.value ? "primary" : "outline"}
            onClick={() => update({ ...filters, state: f.value })}
          >
            {f.label}
          </Button>
        ))}
        <label className="ml-auto flex items-center gap-2 text-sm">
          <span className="sr-only">Filter by title or path</span>
          <input
            className="h-8 rounded-md border border-border-input bg-surface-raised px-2"
            placeholder="Filter by title or path"
            value={filters.q}
            onChange={(e) => update({ ...filters, q: e.target.value })}
          />
        </label>
      </div>
      <table className="w-full text-sm max-md:block">
        <thead className="text-left text-fg-muted max-md:hidden">
          <tr>
            <th className="py-2">Title</th>
            <th>Path</th>
            <th>Status</th>
            <th>Vectors</th>
            <th>Indexed</th>
            <th />
          </tr>
        </thead>
        <tbody className="max-md:block">
          {rows.map((r) => {
            const badge = badgeFor(r);
            return (
              <tr key={r.id} className="border-t border-border align-top max-md:block max-md:py-2">
                <td className="py-2 pr-2 max-md:block max-md:py-0">{r.title ?? r.path}</td>
                <td className="max-md:block pr-2 font-mono break-all">{r.path}</td>
                <td className="max-md:block pr-2">
                  <span
                    className={cn(
                      "inline-block rounded-md border px-2 py-0.5 text-xs",
                      TONES[badge.tone],
                    )}
                  >
                    {badge.label}
                  </span>
                </td>
                <td className="max-md:block pr-2">{`Embedded ${r.embedded}/${r.chunks}`}</td>
                <td className="max-md:block pr-2">
                  {r.indexed_at ? relativeTime(r.indexed_at) : "—"}
                </td>
                <td className="max-md:block">
                  {canRetry(r) ? (
                    <Button
                      size="sm"
                      variant="outline"
                      aria-label={`Retry ${r.title ?? r.path}`}
                      onClick={() => void onRetry(r)}
                    >
                      Retry
                    </Button>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {listError ? (
        <p role="alert" className="text-sm text-danger-fg">
          Couldn't load the list.
        </p>
      ) : null}
      {hasMore ? (
        <Button variant="outline" onClick={onLoadMore}>
          Load more
        </Button>
      ) : null}
    </div>
  );
}
