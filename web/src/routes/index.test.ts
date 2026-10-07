import { isRedirect } from "@tanstack/react-router";
import { describe, expect, it } from "vitest";
import { Route } from "./index";

describe("/ route", () => {
  it("redirects to the digest", () => {
    const beforeLoad = Route.options.beforeLoad as () => void;
    let thrown: unknown;
    try {
      beforeLoad();
    } catch (e) {
      thrown = e;
    }
    expect(isRedirect(thrown)).toBe(true);
    expect((thrown as { options: { to: string } }).options).toMatchObject({ to: "/digest" });
  });
});
