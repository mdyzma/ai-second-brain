import { describe, expect, it } from "vitest";
import {
  ALL_CAUGHT_UP,
  BUSY,
  FAILURES_HINT,
  failedRunLine,
  indexedLine,
  LOAD_ERROR,
  noRunsLine,
  notesWord,
  runningLine,
  summaryLine,
  timedOutLine,
  UNAVAILABLE,
} from "./copy";
import type { Digest } from "./types";

function digest(done: number, failed: number, remaining: number): Digest {
  return {
    nightly_at: "02:00",
    nightly_enabled: true,
    run: {
      id: "r1",
      run_date: "2026-10-07",
      trigger: "schedule",
      status: "complete",
      timed_out: false,
      unavailable: false,
      error: null,
      started_at: "2026-10-07T02:00:00Z",
      finished_at: "2026-10-07T03:00:00Z",
      window_start: null,
      queued_new: 10,
      queued_failed: 2,
      done,
    },
    review: {
      remaining,
      open_total: remaining,
      entities: { count: remaining, by_type: {}, top: [] },
      links: { count: 0, top: [] },
    },
    failed: { count: failed, items: [] },
    indexed: { created: 0, changed: 0, deleted: 0, since_beginning: true },
  };
}

describe("digest copy", () => {
  it("pluralises notes", () => {
    expect(notesWord(1)).toBe("note");
    expect(notesWord(0)).toBe("notes");
    expect(notesWord(2)).toBe("notes");
  });

  it("builds the summary line", () => {
    expect(summaryLine(digest(1, 0, 0))).toBe("Last night: 1 note read, 0 failed, 0 to review.");
    expect(summaryLine(digest(42, 3, 18))).toBe(
      "Last night: 42 notes read, 3 failed, 18 to review.",
    );
  });

  it("builds the running line from done and both queued counts", () => {
    expect(runningLine(digest(3, 0, 0))).toBe("Reading notes: 3 of 12.");
  });

  it("uses the exact constant strings", () => {
    expect(UNAVAILABLE).toBe(
      "Extraction is off: no Ollama endpoint is configured (SB_OLLAMA_ENDPOINTS).",
    );
    expect(ALL_CAUGHT_UP).toBe("All caught up.");
    expect(`${FAILURES_HINT.before}${FAILURES_HINT.command}${FAILURES_HINT.after}`).toBe(
      "Retried next night, or run just graph-extract --failed now.",
    );
    expect(FAILURES_HINT.command).toBe("just graph-extract --failed");
    expect(BUSY).toBe("A run is already in progress.");
    expect(LOAD_ERROR).toBe("Couldn't load the digest. Try again.");
  });

  it("fills the templated lines", () => {
    expect(timedOutLine(8)).toBe(
      "Stopped waiting after 8 hours. Remaining notes will finish in the background.",
    );
    expect(failedRunLine("db_error")).toBe(
      "Last night's run failed to start (db_error). It will try again at the next check.",
    );
    expect(noRunsLine("02:00")).toBe(
      "No nightly run yet. The first starts at 02:00, or press Run now.",
    );
  });

  it("builds the indexed line", () => {
    expect(indexedLine({ created: 4, changed: 2, deleted: 1, since_beginning: false })).toBe(
      "4 added, 2 changed, 1 deleted since the previous run",
    );
    expect(indexedLine({ created: 4, changed: 0, deleted: 0, since_beginning: true })).toBe(
      "4 added, 0 changed, 0 deleted since the beginning",
    );
  });
});
