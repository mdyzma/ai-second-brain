import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { recentQueries } from "./labels";
import { useRememberQuery } from "./useRememberQuery";

type P = { q: string; ok: boolean; stale: boolean };

const hook = (initialProps: P) =>
  renderHook((p: P) => useRememberQuery(p.q, { isSuccess: p.ok, isPlaceholderData: p.stale }), {
    initialProps,
  });

describe("useRememberQuery", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it("stores a query once it has been stable for 2 s after fresh data", () => {
    const { result, rerender } = hook({ q: "nas", ok: false, stale: false });
    rerender({ q: "nas", ok: true, stale: true });
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(recentQueries()).toEqual([]);
    rerender({ q: "nas", ok: true, stale: false });
    act(() => {
      vi.advanceTimersByTime(1999);
    });
    expect(recentQueries()).toEqual([]);
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(recentQueries()).toEqual(["nas"]);
    expect(result.current.recent).toEqual(["nas"]);
  });

  it("never stores a debounced prefix that was typed past", () => {
    const { rerender } = hook({ q: "ko", ok: true, stale: false });
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    rerender({ q: "kopie", ok: true, stale: false });
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    rerender({ q: "kopie zapasowe", ok: true, stale: false });
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(recentQueries()).toEqual(["kopie zapasowe"]);
  });

  it("does not store a failed query", () => {
    hook({ q: "boom", ok: false, stale: true });
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(recentQueries()).toEqual([]);
  });

  it("remember() stores a query right away", () => {
    const { result } = hook({ q: "", ok: false, stale: false });
    act(() => result.current.remember(" proxmox "));
    expect(recentQueries()).toEqual(["proxmox"]);
    expect(result.current.recent).toEqual(["proxmox"]);
  });
});
