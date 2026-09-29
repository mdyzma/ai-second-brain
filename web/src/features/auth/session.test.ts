import { describe, expect, it } from "vitest";
import { interpretLoginResponse, safeRedirect } from "./session";

describe("interpretLoginResponse", () => {
  it.each([
    [204, null, { ok: true }],
    [401, null, { ok: false, reason: "invalid" }],
    [422, null, { ok: false, reason: "invalid" }],
    [429, "42", { ok: false, reason: "throttled", retryAfter: 42 }],
    [429, null, { ok: false, reason: "throttled", retryAfter: 60 }],
    [429, "soon", { ok: false, reason: "throttled", retryAfter: 60 }],
    [503, null, { ok: false, reason: "unreachable" }],
    [500, null, { ok: false, reason: "unreachable" }],
    [403, null, { ok: false, reason: "unreachable" }],
  ] as const)("status %i (Retry-After %s)", (status, retryAfter, expected) => {
    expect(interpretLoginResponse(status, retryAfter)).toEqual(expected);
  });
});

describe("safeRedirect", () => {
  it.each([
    ["/search", "/search"],
    ["/projects?x=1#y", "/projects?x=1#y"],
    [undefined, "/ask"],
    [42, "/ask"],
    ["", "/ask"],
    ["https://evil.example", "/ask"],
    ["//evil.example", "/ask"],
    ["/\\evil.example", "/ask"],
    ["/login", "/ask"],
    ["/login?redirect=/x", "/ask"],
    ["javascript:alert(1)", "/ask"],
  ])("%s → %s", (input, expected) => {
    expect(safeRedirect(input)).toBe(expected);
  });
});
