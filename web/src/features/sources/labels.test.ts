import { describe, expect, it } from "vitest";
import { canRetry, refreshMessage, relativeTime } from "./labels";
import type { SourceRow } from "./types";

const NOW = Date.parse("2026-09-30T12:00:00Z");
const ago = (s: number) => new Date(NOW - s * 1000).toISOString();
const row = (over: Partial<SourceRow>): SourceRow => ({
  id: "a",
  title: "t",
  path: "t.md",
  state: "indexed",
  error: null,
  indexed_at: null,
  chunks: 2,
  embedded: 2,
  ...over,
});

describe("relativeTime", () => {
  it("formats each range, flooring", () => {
    expect(relativeTime(ago(5), NOW)).toBe("just now");
    expect(relativeTime(ago(59), NOW)).toBe("just now");
    expect(relativeTime(ago(119), NOW)).toBe("1 min ago");
    expect(relativeTime(ago(3 * 3600 + 1800), NOW)).toBe("3 h ago");
    expect(relativeTime(ago(2 * 86400 + 80000), NOW)).toBe("2 d ago");
  });
  it("treats the future as just now and an invalid date as a dash", () => {
    expect(relativeTime(ago(-500), NOW)).toBe("just now");
    expect(relativeTime("not a date", NOW)).toBe("—");
  });
});

describe("canRetry", () => {
  it("applies to failed rows and partly embedded indexed rows only", () => {
    expect(canRetry(row({ state: "failed" }))).toBe(true);
    expect(canRetry(row({ embedded: 1 }))).toBe(true);
    expect(canRetry(row({}))).toBe(false);
    expect(canRetry(row({ state: "pending" }))).toBe(false);
    expect(canRetry(row({ state: "deleted" }))).toBe(false);
  });
  it("hides Retry for read errors, which only a changed file can fix", () => {
    expect(canRetry(row({ state: "failed", error: "index_error" }))).toBe(true);
    expect(canRetry(row({ state: "failed", error: "too_large" }))).toBe(false);
    expect(canRetry(row({ state: "failed", error: "encoding" }))).toBe(false);
  });
});

describe("refreshMessage", () => {
  it("never shows server text", () => {
    expect(refreshMessage(503)).toBe("The database is unavailable. Showing the last known state.");
    expect(refreshMessage(0)).toBe("Can't reach the server. Showing the last known state.");
    expect(refreshMessage(500)).toBe("Couldn't refresh. Showing the last known state.");
  });
});
