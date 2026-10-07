import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId } from "react";
import { Button, buttonVariants } from "@/design-system/ui/button";
import { BADGE } from "@/features/graph/EntitiesScreen";
import { RELATION_LABEL, TYPE_LABEL } from "@/features/graph/labels";
import type { EntityType, Relation } from "@/features/graph/types";
import { HttpError, statusOf } from "@/features/sources/api";
import { digestQuery, nightlyRunsQuery, useStartNightlyRun } from "./api";
import {
  ALL_CAUGHT_UP,
  BUSY,
  FAILURES_HINT,
  failedRunLine,
  indexedLine,
  LOAD_ERROR,
  noRunsLine,
  runningLine,
  START_ERROR,
  summaryLine,
  timedOutLine,
  UNAVAILABLE,
  waitedHours,
} from "./copy";
import type { Digest } from "./types";

const SELECT_CLASS =
  "h-10 rounded-md border border-border-input bg-surface-raised px-2 text-sm text-fg";
const SECTION = "space-y-3 rounded-lg border border-border bg-surface-raised p-4";
const COUNT_PILL = "rounded-full bg-surface px-2 py-0.5 text-sm font-medium text-fg-muted";

export type DigestScreenProps = {
  /** The run date to show (YYYY-MM-DD); undefined shows the latest run. */
  date: string | undefined;
  onDate: (date: string | undefined) => void;
};

export function DigestScreen({ date, onDate }: DigestScreenProps) {
  const digest = useQuery(digestQuery(date));
  const runs = useQuery(nightlyRunsQuery);
  const start = useStartNightlyRun();
  const pickerId = useId();

  const run = digest.data?.run ?? null;
  const dates = [...new Set((runs.data?.runs ?? []).map((r) => r.run_date))];
  const selected = date ?? run?.run_date ?? "";
  if (selected && !dates.includes(selected)) dates.unshift(selected);
  const busy = start.error instanceof HttpError && start.error.status === 409;

  return (
    <div className="max-w-3xl space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Digest</h1>
          {run ? (
            <p className="text-sm text-fg-muted">
              {run.run_date} · {run.trigger === "manual" ? "Manual run" : "Scheduled run"}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-end gap-2">
          {dates.length ? (
            <div className="flex flex-col gap-1">
              <label htmlFor={pickerId} className="text-xs text-fg-muted">
                Run date
              </label>
              <select
                id={pickerId}
                className={SELECT_CLASS}
                value={selected}
                onChange={(e) => {
                  const next = e.target.value;
                  onDate(next === runs.data?.runs[0]?.run_date ? undefined : next);
                }}
              >
                {dates.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          <Button
            disabled={run?.status === "running" || start.isPending}
            onClick={() => start.mutate()}
          >
            Run now
          </Button>
        </div>
      </header>
      <p role="status" aria-live="polite" className="text-sm text-fg-muted">
        {busy ? BUSY : null}
      </p>
      {start.isError && !busy ? (
        <p role="alert" className="text-sm text-danger-fg">
          {START_ERROR}
        </p>
      ) : null}
      {digest.data ? (
        <DigestBody digest={digest.data} />
      ) : digest.isError ? (
        statusOf(digest.error) === 404 && date ? (
          <p className="text-sm text-fg-muted">No nightly run on {date}.</p>
        ) : (
          <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-danger-fg">
            <span>{LOAD_ERROR}</span>
            <Button size="sm" variant="outline" onClick={() => void digest.refetch()}>
              Retry
            </Button>
          </div>
        )
      ) : (
        <p className="text-sm text-fg-muted">Loading…</p>
      )}
    </div>
  );
}

function statusLines(d: Digest): string[] {
  const run = d.run;
  if (!run) return [noRunsLine(d.nightly_at)];
  if (run.status === "failed") return [failedRunLine(run.error ?? "unknown")];
  if (run.status === "running") return [runningLine(d)];
  const lines = [run.unavailable ? UNAVAILABLE : summaryLine(d)];
  if (run.timed_out) lines.push(timedOutLine(waitedHours(run)));
  return lines;
}

function DigestBody({ digest }: { digest: Digest }) {
  return (
    <div className="space-y-5">
      <div aria-live="polite" className="space-y-1 text-sm">
        {statusLines(digest).map((line) => (
          <p key={line}>{line}</p>
        ))}
      </div>
      {digest.review ? <ToReview review={digest.review} /> : null}
      {digest.failed && digest.failed.count > 0 ? <Failed failed={digest.failed} /> : null}
      {digest.indexed ? (
        <p className="text-sm text-fg-muted">{indexedLine(digest.indexed)}</p>
      ) : null}
    </div>
  );
}

function ToReview({ review }: { review: NonNullable<Digest["review"]> }) {
  const headingId = useId();
  const { entities, links } = review;
  return (
    <section aria-labelledby={headingId} className={SECTION}>
      <h2 id={headingId} className="flex items-center gap-2 text-lg font-semibold">
        To review{" "}
        <span data-testid="remaining" className={COUNT_PILL}>
          {review.remaining}
        </span>
      </h2>
      {review.remaining === 0 ? (
        <p className="text-sm text-fg-muted">{ALL_CAUGHT_UP}</p>
      ) : (
        <>
          {Object.keys(entities.by_type).length ? (
            <ul aria-label="Entities by type" className="flex flex-wrap gap-2">
              {Object.entries(entities.by_type).map(([type, n]) => (
                <li key={type} className={BADGE}>
                  {TYPE_LABEL[type as EntityType] ?? type}: {n}
                </li>
              ))}
            </ul>
          ) : null}
          {entities.top.length ? (
            <div className="space-y-2">
              <h3 className="text-sm font-medium">Entities ({entities.count})</h3>
              <ul className="space-y-2">
                {entities.top.map((e) => (
                  <li key={e.id}>
                    <Link
                      to="/entities/$entityId"
                      params={{ entityId: e.id }}
                      className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-surface p-2 text-sm hover:bg-surface-raised focus-visible:outline-2 focus-visible:outline-ring"
                    >
                      <span className="font-medium">{e.name}</span>
                      <span className={BADGE}>{TYPE_LABEL[e.type]}</span>
                      {e.source_title || e.source_path ? (
                        <span className="ml-auto text-xs text-fg-muted">
                          {e.source_title ?? e.source_path}
                        </span>
                      ) : null}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {links.top.length ? (
            <div className="space-y-2">
              <h3 className="text-sm font-medium">Links ({links.count})</h3>
              <ul className="space-y-1 text-sm">
                {links.top.map((l) => {
                  const relation = RELATION_LABEL[l.relation as Relation]?.[0] ?? l.relation;
                  return (
                    <li
                      key={l.id}
                    >{`${l.subject ?? "A note"} — ${relation} — ${l.object ?? ""}`}</li>
                  );
                })}
              </ul>
            </div>
          ) : null}
        </>
      )}
      <div className="flex flex-wrap gap-2">
        <Link to="/review" className={buttonVariants({ variant: "outline", size: "sm" })}>
          Review all
        </Link>
        <Link
          to="/review"
          search={{ tab: "links" }}
          className={buttonVariants({ variant: "outline", size: "sm" })}
        >
          Review links
        </Link>
      </div>
    </section>
  );
}

function Failed({ failed }: { failed: NonNullable<Digest["failed"]> }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className={SECTION}>
      <h2 id={headingId} className="flex items-center gap-2 text-lg font-semibold">
        Failed <span className={COUNT_PILL}>{failed.count}</span>
      </h2>
      <ul className="space-y-1 text-sm">
        {failed.items.map((f) => (
          <li key={f.path} className="flex flex-wrap items-center gap-2">
            <code className="font-mono text-xs">{f.path}</code>
            {f.error ? <span className="text-xs text-fg-muted">{f.error}</span> : null}
          </li>
        ))}
      </ul>
      <p className="text-sm text-fg-muted">
        {FAILURES_HINT.before}
        <code className="font-mono text-xs">{FAILURES_HINT.command}</code>
        {FAILURES_HINT.after}
      </p>
    </section>
  );
}
