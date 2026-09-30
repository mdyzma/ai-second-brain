import { describe, expect, it } from "vitest";
import { HttpError, pollInterval, rowsOf, statusOf } from "./api";

const r = (id: string) => ({
  id,
  title: null,
  path: `${id}.md`,
  state: "indexed" as const,
  error: null,
  indexed_at: null,
  chunks: 0,
  embedded: 0,
});

describe("rowsOf", () => {
  it("flattens pages and drops repeated ids", () => {
    const pages = [
      { items: [r("a"), r("b")], next_cursor: "x" },
      { items: [r("b"), r("c")], next_cursor: null },
    ];
    expect(rowsOf({ pages }).map((x) => x.id)).toEqual(["a", "b", "c"]);
    expect(rowsOf(undefined)).toEqual([]);
  });
});

describe("pollInterval", () => {
  const base = { revisions: { pending: 0 }, last_run: null };
  it("polls fast while work is pending, scanning or queued", () => {
    expect(pollInterval(base, false)).toBe(60_000);
    expect(pollInterval({ ...base, revisions: { pending: 2 } }, false)).toBe(10_000);
    expect(pollInterval(base, true)).toBe(10_000);
    expect(
      pollInterval({ ...base, last_run: { trigger: "manual", finished_at: null } }, false),
    ).toBe(10_000);
    expect(pollInterval(undefined, false)).toBe(60_000);
  });
});

describe("statusOf", () => {
  it("reads an HttpError status and maps anything else to 0", () => {
    expect(statusOf(new HttpError(503))).toBe(503);
    expect(statusOf(new TypeError("Failed to fetch"))).toBe(0);
  });
});
