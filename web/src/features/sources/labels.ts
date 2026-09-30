import type { SourceRow, SourcesSummary } from "./types";

export type Tone = "pending" | "searchable" | "failed" | "neutral";

export function badgeFor(row: SourceRow): { label: string; tone: Tone } {
  switch (row.state) {
    case "pending":
      return { label: "Waiting", tone: "pending" };
    case "failed":
      return { label: `Failed · ${row.error ?? "unknown"}`, tone: "failed" };
    case "deleted":
      return { label: "Deleted", tone: "neutral" };
    default:
      return row.embedded < row.chunks
        ? { label: "Text only", tone: "pending" }
        : { label: "Searchable", tone: "searchable" };
  }
}

export function bannersFor(summary: SourcesSummary): string[] {
  if (!summary.vault.configured) {
    return [
      "No vault configured. Set SB_VAULT_PATH to your Obsidian vault and restart the worker.",
    ];
  }
  const banners: string[] = [];
  const run = summary.last_run;
  if (!summary.vault.readable || run?.outcome === "vault_unavailable") {
    banners.push("The vault folder can't be read. Nothing was deleted.");
  }
  if (run?.outcome === "guard_tripped") {
    const missing = run.counts.missing ?? 0;
    banners.push(
      `The last scan found ${missing} notes missing and deleted nothing. Check the vault path, then run \`ai-second-brain vault reconcile --allow-mass-delete\`.`,
    );
  }
  if (summary.embedding.last_error === "embed_model_missing") {
    banners.push(
      `The embedding model isn't installed. Run \`ollama pull ${summary.embedding.model}\` on the embedding host.`,
    );
  }
  if (summary.embedding.host_reachable === false) {
    banners.push(
      "The embedding host is unreachable. Notes stay searchable by text; vectors are added when it's back.",
    );
  }
  return banners;
}

export function relativeTime(iso: string, now: number = Date.now()): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "—";
  const seconds = Math.max(0, Math.floor((now - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours} h ago` : `${Math.floor(hours / 24)} d ago`;
}

const DB_DOWN = "The database is unavailable. Try again in a moment.";
const UNREACHABLE = "Can't reach the server.";
const SESSION_ENDED = "Your session ended. Sign in again.";

/** Plain-language text for a failed Retry; never shows server text. Status 0 = network failure. */
export function retryMessage(status: number): string {
  switch (status) {
    case 404:
      return "That note is no longer in the index.";
    case 409:
      return "There is nothing to retry for this note.";
    case 401:
      return SESSION_ENDED;
    case 503:
      return DB_DOWN;
    case 0:
      return UNREACHABLE;
    default:
      return "Couldn't queue the retry. Try again.";
  }
}

/** Plain-language text for a failed Scan now. */
export function scanMessage(status: number): string {
  switch (status) {
    case 409:
      return "No vault is configured, so there is nothing to scan.";
    case 401:
      return SESSION_ENDED;
    case 503:
      return DB_DOWN;
    case 0:
      return UNREACHABLE;
    default:
      return "Couldn't start the scan. Try again.";
  }
}

export function canRetry(row: SourceRow): boolean {
  return row.state === "failed" || (row.state === "indexed" && row.embedded < row.chunks);
}

/** Note shown above a screen that still has older data when a background refresh failed. */
export function refreshMessage(status: number): string {
  const tail = "Showing the last known state.";
  if (status === 503) return `The database is unavailable. ${tail}`;
  if (status === 0) return `Can't reach the server. ${tail}`;
  return `Couldn't refresh. ${tail}`;
}
