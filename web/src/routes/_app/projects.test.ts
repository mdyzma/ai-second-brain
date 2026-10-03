import { isRedirect } from "@tanstack/react-router";
import { describe, expect, it } from "vitest";
import { Route } from "./projects";

describe("/projects route", () => {
  it("redirects to the project entities list", () => {
    const beforeLoad = Route.options.beforeLoad as () => void;
    let thrown: unknown;
    try {
      beforeLoad();
    } catch (e) {
      thrown = e;
    }
    expect(isRedirect(thrown)).toBe(true);
    expect((thrown as { options: { to: string; search: unknown } }).options).toMatchObject({
      to: "/entities",
      search: { type: "project" },
    });
  });
});
