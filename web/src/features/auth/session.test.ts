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
    [undefined, "/digest"],
    [42, "/digest"],
    ["", "/digest"],
    ["https://evil.example", "/digest"],
    ["//evil.example", "/digest"],
    ["/\\evil.example", "/digest"],
    ["/login", "/digest"],
    ["/login?redirect=/x", "/digest"],
    ["javascript:alert(1)", "/digest"],
    ["/\t/evil.example", "/digest"],
    ["/\n/evil.example", "/digest"],
    ["/\r/evil.example", "/digest"],
    ["/\u007f/x", "/digest"],
    ["/%09/evil.example", "/%09/evil.example"],
    ["/LOGIN", "/digest"],
    ["/login#x", "/digest"],
  ])("%s → %s", (input, expected) => {
    expect(safeRedirect(input)).toBe(expected);
  });
});
