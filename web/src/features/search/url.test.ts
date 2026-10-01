import { describe, expect, it } from "vitest";
import { historyStep, parseSearch, toSearchParams } from "./url";

describe("search history steps", () => {
  it("pushes a committed change on top of a committed entry", () => {
    expect(historyStep(false, "commit")).toEqual({ replace: false, draft: false });
  });
  it("pushes the first typing update, marked as a draft", () => {
    expect(historyStep(false, "typing")).toEqual({ replace: false, draft: true });
  });
  it("replaces a draft entry with further typing", () => {
    expect(historyStep(true, "typing")).toEqual({ replace: true, draft: true });
  });
  it("turns a draft into a committed entry in place", () => {
    expect(historyStep(true, "commit")).toEqual({ replace: true, draft: false });
  });
});

describe("search url state", () => {
  it("round-trips state through the URL", () => {
    const state = { q: "nas", folder: "Projects", tags: ["homelab", "nas"] };
    expect(parseSearch(toSearchParams(state))).toEqual(state);
    expect(parseSearch({ tag: "x" })).toEqual({ q: "", tags: ["x"] });
  });
  it("omits empty values", () => {
    expect(toSearchParams({ q: "", tags: [] })).toEqual({});
  });
});
