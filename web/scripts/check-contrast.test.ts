import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { checkTokens } from "./check-contrast.ts";

const tokensCss = readFileSync(
  resolve(import.meta.dirname, "../src/design-system/tokens.css"),
  "utf8",
);

describe("checkTokens", () => {
  it("passes for the real tokens in both themes", () => {
    const { failures, checked } = checkTokens(tokensCss);
    expect(failures).toEqual([]);
    expect(checked).toBeGreaterThan(100);
  });

  it("reports a low-contrast text pair with theme and ratio", () => {
    const css = `:root { --sb-bg: oklch(0.99 0 0); --sb-surface: oklch(0.97 0 0);
      --sb-surface-raised: oklch(1 0 0); --sb-text: oklch(0.8 0 0); --sb-text-muted: oklch(0.3 0 0);
      --sb-accent: oklch(0.4 0 0); --sb-accent-fg: oklch(0.99 0 0);
      --sb-border-input: oklch(0.5 0 0); --sb-focus-ring: oklch(0.5 0 0); }`;
    const { failures } = checkTokens(css);
    expect(failures.some((f) => f.theme === "light" && f.fg === "--sb-text" && f.min === 4.5)).toBe(
      true,
    );
  });

  it("resolves var() aliases before measuring", () => {
    const css = `:root { --sb-bg: oklch(0.99 0 0); --sb-surface: oklch(0.97 0 0);
      --sb-surface-raised: oklch(1 0 0); --sb-text: oklch(0.2 0 0); --sb-text-muted: oklch(0.4 0 0);
      --sb-accent: oklch(0.4 0 0); --sb-accent-fg: oklch(0.99 0 0);
      --sb-border-input: oklch(0.5 0 0); --sb-focus-ring: oklch(0.5 0 0);
      --sb-x-fg: oklch(0.95 0 0); --sb-x-bg: oklch(0.99 0 0); --sb-node-y-fg: var(--sb-x-fg);
      --sb-node-y-bg: var(--sb-x-bg); }`;
    const { failures } = checkTokens(css);
    expect(failures.some((f) => f.fg === "--sb-node-y-fg")).toBe(true);
  });

  it("fails on an unresolvable token", () => {
    const css = `:root { --sb-bg: oklch(0.99 0 0); --sb-text: var(--sb-missing); }`;
    expect(checkTokens(css).failures.length).toBeGreaterThan(0);
  });

  it("reports a border that passes on bg but fails on surface", () => {
    const css = `:root { --sb-bg: oklch(1 0 0); --sb-surface: oklch(0.6 0 0);
      --sb-surface-raised: oklch(1 0 0); --sb-text: oklch(0 0 0); --sb-text-muted: oklch(0 0 0);
      --sb-accent: oklch(0 0 0); --sb-accent-fg: oklch(1 0 0);
      --sb-border-input: oklch(0 0 0); --sb-focus-ring: oklch(0 0 0);
      --sb-x-border: oklch(0.6 0 0); }`;
    const { failures } = checkTokens(css);
    expect(
      failures.some((f) => f.fg === "--sb-x-border" && f.bg === "--sb-surface" && f.min === 3),
    ).toBe(true);
    expect(failures.some((f) => f.fg === "--sb-x-border" && f.bg === "--sb-bg")).toBe(false);
  });
});
