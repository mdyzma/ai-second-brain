import { describe, expect, it } from "vitest";
import { parseSearch, toSearchParams } from "./url";

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
