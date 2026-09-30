import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  SCAN_TIMEOUT_MS,
  scanStatus,
  serverScanning,
  useScanQueue,
  WORKER_NOT_PICKED_UP,
} from "./scan";

const OLD = {
  trigger: "schedule",
  started_at: "2026-09-30T10:00:00Z",
  picked_up_at: "2026-09-30T10:00:00Z",
  finished_at: "2026-09-30T10:00:02Z",
};
const NEW = {
  trigger: "manual",
  started_at: "2026-09-30T10:05:00Z",
  picked_up_at: "2026-09-30T10:05:01Z",
  finished_at: "2026-09-30T10:05:02Z",
};
const RUNNING = { ...NEW, finished_at: null };
/** The row POST /sources/reconcile creates before any worker has the job. */
const UNCLAIMED = { ...NEW, picked_up_at: null, finished_at: null };
type Run = typeof OLD | typeof RUNNING | typeof UNCLAIMED;

describe("scanStatus", () => {
  const queued = { after: OLD.started_at, at: 1000 };
  it("is idle when nothing is queued", () => {
    expect(scanStatus(null, OLD, 5000)).toBe("idle");
  });
  it("stays pending while only the older run has finished", () => {
    expect(scanStatus(queued, OLD, 2000)).toBe("pending");
  });
  it("stays pending while the newer run is still running", () => {
    expect(scanStatus(queued, RUNNING, 2000)).toBe("pending");
  });
  it("is done when a newer run finished", () => {
    expect(scanStatus(queued, NEW, 2000)).toBe("done");
  });
  it("does not time out once a newer run has started", () => {
    expect(scanStatus(queued, RUNNING, 1000 + SCAN_TIMEOUT_MS * 5)).toBe("pending");
  });
  it("times out after 60 s", () => {
    expect(scanStatus(queued, OLD, 1000 + SCAN_TIMEOUT_MS)).toBe("timed_out");
  });
  it("waits for the API-created run to be picked up, then times out", () => {
    expect(scanStatus(queued, UNCLAIMED, 2000)).toBe("pending");
    expect(scanStatus(queued, UNCLAIMED, 1000 + SCAN_TIMEOUT_MS)).toBe("timed_out");
  });
  it("treats any finished run as new when there was none before", () => {
    expect(scanStatus({ after: null, at: 0 }, OLD, 10)).toBe("done");
  });
});

describe("useScanQueue", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("clears on a newer finished run", () => {
    const { result, rerender } = renderHook(({ run }) => useScanQueue(run), {
      initialProps: { run: OLD as Run | null },
    });
    act(() => result.current.start());
    expect(result.current.queued).toBe(true);
    rerender({ run: OLD });
    expect(result.current.queued).toBe(true);
    rerender({ run: NEW });
    expect(result.current.queued).toBe(false);
    expect(result.current.notice).toBeNull();
  });

  it("clears with a notice after 60 s", () => {
    const { result } = renderHook(() => useScanQueue(OLD));
    act(() => result.current.start());
    act(() => {
      vi.advanceTimersByTime(SCAN_TIMEOUT_MS - 1);
    });
    expect(result.current.queued).toBe(true);
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.queued).toBe(false);
    expect(result.current.notice).toBe(WORKER_NOT_PICKED_UP);
    expect(WORKER_NOT_PICKED_UP).toBe("The worker hasn't picked this up yet.");
  });

  it("times out when the API-created run is never picked up", () => {
    const { result, rerender } = renderHook(({ run }) => useScanQueue(run), {
      initialProps: { run: OLD as Run },
    });
    act(() => result.current.start());
    rerender({ run: UNCLAIMED });
    act(() => {
      vi.advanceTimersByTime(SCAN_TIMEOUT_MS);
    });
    expect(result.current.queued).toBe(false);
    expect(result.current.notice).toBe(WORKER_NOT_PICKED_UP);
  });

  it("does not time out once the worker picked the run up", () => {
    const { result, rerender } = renderHook(({ run }) => useScanQueue(run), {
      initialProps: { run: OLD as Run },
    });
    act(() => result.current.start());
    rerender({ run: UNCLAIMED });
    rerender({ run: RUNNING });
    act(() => {
      vi.advanceTimersByTime(SCAN_TIMEOUT_MS * 3);
    });
    expect(result.current.queued).toBe(true);
    expect(result.current.notice).toBeNull();
  });
});

describe("serverScanning", () => {
  it("is true only for a manual run a worker has picked up and not finished", () => {
    expect(serverScanning(RUNNING)).toBe(true);
    expect(serverScanning(UNCLAIMED)).toBe(false);
    expect(serverScanning(NEW)).toBe(false);
    expect(serverScanning({ ...RUNNING, trigger: "schedule" })).toBe(false);
    expect(serverScanning(null)).toBe(false);
  });
});
