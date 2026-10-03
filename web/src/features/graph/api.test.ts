import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import {
  GRAPH_POLL_FAST_MS,
  GRAPH_POLL_SLOW_MS,
  graphKeys,
  graphPollInterval,
  refreshOnProgress,
} from "./api";

const counts = (pending: number, extracted: number, failed = 0) => ({
  revisions: { pending, extracted, failed },
});

describe("graphPollInterval", () => {
  it("is fast while extract jobs are queued", () => {
    expect(graphPollInterval({ queued: 2 })).toBe(GRAPH_POLL_FAST_MS);
  });
  it("is slow when nothing is queued, even with notes not yet extracted", () => {
    expect(graphPollInterval({ queued: 0, ...counts(3, 1) })).toBe(GRAPH_POLL_SLOW_MS);
    expect(graphPollInterval(undefined)).toBe(GRAPH_POLL_SLOW_MS);
  });
});

describe("refreshOnProgress", () => {
  const setup = () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries").mockResolvedValue();
    return { qc, spy };
  };
  it("does not invalidate on the first load or unchanged counts", () => {
    const { qc, spy } = setup();
    const first = refreshOnProgress(qc, null, counts(4, 1));
    refreshOnProgress(qc, first, counts(4, 1));
    expect(spy).not.toHaveBeenCalled();
  });
  it("invalidates both review lists when the counts change", () => {
    const { qc, spy } = setup();
    const first = refreshOnProgress(qc, null, counts(4, 1));
    refreshOnProgress(qc, first, counts(3, 2));
    expect(spy).toHaveBeenCalledWith({ queryKey: graphKeys.entities });
    expect(spy).toHaveBeenCalledWith({ queryKey: graphKeys.links });
  });
});
