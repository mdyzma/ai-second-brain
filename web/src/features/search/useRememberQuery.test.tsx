import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { recentQueries } from "./labels";
import { useRememberQuery } from "./useRememberQuery";

describe("useRememberQuery", () => {
  beforeEach(() => localStorage.clear());

  it("stores a query only once it succeeded with fresh data", () => {
    const { result, rerender } = renderHook(
      (p: { ok: boolean; stale: boolean }) =>
        useRememberQuery("nas", { isSuccess: p.ok, isPlaceholderData: p.stale }),
      { initialProps: { ok: false, stale: false } },
    );
    expect(recentQueries()).toEqual([]);
    rerender({ ok: true, stale: true });
    expect(recentQueries()).toEqual([]);
    rerender({ ok: true, stale: false });
    expect(recentQueries()).toEqual(["nas"]);
    expect(result.current.recent).toEqual(["nas"]);
  });

  it("does not store a failed query", () => {
    renderHook(() => useRememberQuery("boom", { isSuccess: false, isPlaceholderData: true }));
    expect(recentQueries()).toEqual([]);
  });
});
