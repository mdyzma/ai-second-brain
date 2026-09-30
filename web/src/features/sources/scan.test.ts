import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SCAN_TIMEOUT_MS, scanStatus, useScanQueue, WORKER_NOT_PICKED_UP } from "./scan";

const OLD = { started_at: "2026-09-30T10:00:00Z", finished_at: "2026-09-30T10:00:02Z" };
const NEW = { started_at: "2026-09-30T10:05:00Z", finished_at: "2026-09-30T10:05:02Z" };
const RUNNING = { started_at: "2026-09-30T10:05:00Z", finished_at: null };

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
  it("treats any finished run as new when there was none before", () => {
    expect(scanStatus({ after: null, at: 0 }, OLD, 10)).toBe("done");
  });
});

describe("useScanQueue", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("clears on a newer finished run", () => {
    const { result, rerender } = renderHook(({ run }) => useScanQueue(run), {
      initialProps: { run: OLD as typeof OLD | null },
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
});
