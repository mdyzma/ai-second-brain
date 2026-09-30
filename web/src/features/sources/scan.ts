import { useEffect, useState } from "react";

export const SCAN_TIMEOUT_MS = 60_000;
export const WORKER_NOT_PICKED_UP = "The worker hasn't picked this up yet.";

export type Queued = { after: string | null; at: number };
export type RunLike = { started_at: string; finished_at: string | null };
export type ScanStatus = "idle" | "pending" | "done" | "timed_out";

/** `after` is the started_at of the last run when the scan was queued; `at` is when. */
export function scanStatus(
  queued: Queued | null,
  lastRun: RunLike | null,
  now: number,
): ScanStatus {
  if (queued === null) return "idle";
  const newer = lastRun !== null && lastRun.started_at !== queued.after;
  if (newer && lastRun.finished_at) return "done";
  if (newer) return "pending"; // picked up; a big vault can take minutes
  return now - queued.at >= SCAN_TIMEOUT_MS ? "timed_out" : "pending";
}

export function useScanQueue(lastRun: RunLike | null) {
  const [queued, setQueued] = useState<Queued | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (queued === null) return;
    const status = scanStatus(queued, lastRun, Date.now());
    if (status === "done") {
      setQueued(null);
      return;
    }
    const expire = () => {
      setQueued(null);
      setNotice(WORKER_NOT_PICKED_UP);
    };
    if (status === "timed_out") {
      expire();
      return;
    }
    if (lastRun !== null && lastRun.started_at !== queued.after) return; // running
    const timer = setTimeout(expire, queued.at + SCAN_TIMEOUT_MS - Date.now());
    return () => clearTimeout(timer);
  }, [queued, lastRun]);

  return {
    queued: queued !== null,
    notice,
    start: () => {
      setNotice(null);
      setQueued({ after: lastRun?.started_at ?? null, at: Date.now() });
    },
  };
}
