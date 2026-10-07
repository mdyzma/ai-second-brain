import type { Digest, DigestIndexed, NightlyRunSummary } from "./types";

export const UNAVAILABLE =
  "Extraction is off: no Ollama endpoint is configured (SB_OLLAMA_ENDPOINTS).";
export const ALL_CAUGHT_UP = "All caught up.";
export const NOTHING_NEW = "Nothing new from this run.";
/** "Retried next night, or run `just graph-extract --failed` now."; the command renders as code. */
export const FAILURES_HINT = {
  before: "Retried next night, or run ",
  command: "just graph-extract --failed",
  after: " now.",
} as const;
export const BUSY = "A run is already in progress.";
export const LOAD_ERROR = "Couldn't load the digest. Try again.";
export const START_ERROR = "Couldn't start a run. Try again.";
export const NIGHTLY_OFF = "Nightly runs are off (SB_NIGHTLY_ENABLED). Press Run now to start one.";
export const RUN_NOT_FOUND = "That run no longer exists.";

const pad = (n: number) => String(n).padStart(2, "0");

/** A picker label: "2026-10-07 02:00 · Scheduled", the start in local time. */
export function runLabel(
  r: Pick<NightlyRunSummary, "run_date" | "started_at" | "trigger">,
): string {
  const at = new Date(r.started_at);
  const time = `${pad(at.getHours())}:${pad(at.getMinutes())}`;
  return `${r.run_date} ${time} · ${r.trigger === "manual" ? "Manual" : "Scheduled"}`;
}

export function notesWord(n: number): string {
  return n === 1 ? "note" : "notes";
}

export function summaryLine(d: Digest): string {
  const read = d.run?.done ?? 0;
  const failed = d.failed?.count ?? 0;
  const remaining = d.review?.remaining ?? 0;
  return `Last night: ${read} ${notesWord(read)} read, ${failed} failed, ${remaining} to review.`;
}

export function runningLine(d: Digest): string {
  const run = d.run;
  const queued = (run?.queued_new ?? 0) + (run?.queued_failed ?? 0);
  return `Reading notes: ${run?.done ?? 0} of ${queued}.`;
}

export function timedOutLine(hours: number): string {
  return `Stopped waiting after ${hours} hours. Remaining notes will finish in the background.`;
}

export function failedRunLine(error: string): string {
  return `Last night's run failed to start (${error}). It will try again at the next check.`;
}

/** Items awaiting review that earlier runs (or manual extraction) produced. */
export function moreWaitingLine(n: number): string {
  return `${n} more waiting from earlier runs.`;
}

export function noRunsLine(nightlyAt: string): string {
  return `No nightly run yet. The first starts at ${nightlyAt}, or press Run now.`;
}

export function indexedLine(i: DigestIndexed): string {
  const since = i.since_beginning ? "since the beginning" : "since the previous run";
  return `${i.created} added, ${i.changed} changed, ${i.deleted} deleted ${since}`;
}
