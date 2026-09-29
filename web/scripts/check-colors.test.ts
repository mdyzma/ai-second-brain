import { describe, expect, it } from "vitest";
import { findViolations } from "./check-colors.ts";

describe("findViolations", () => {
  it.each([
    `const c = "#ff0000";`,
    `<div className="bg-[#123456]" />`,
    `style={{ color: "rgb(1, 2, 3)" }}`,
    `color: oklch(0.5 0.1 200);`,
    `color: hsl(200 50% 50%);`,
  ])("flags %s", (source) => {
    expect(findViolations(source)).toHaveLength(1);
  });

  it.each([
    `<a href="#main-content">Skip</a>`,
    `<a href="#add-note">Add</a>`,
    `const label = "Step #12";`,
    `<div className="bg-surface text-fg" />`,
    `const text = label(1) + getLabel(2);`,
  ])("ignores %s", (source) => {
    expect(findViolations(source)).toEqual([]);
  });

  it("reports 1-based line numbers", () => {
    expect(findViolations(`ok\nok\ncolor: "#abcdef"`)[0]?.line).toBe(3);
  });
});
