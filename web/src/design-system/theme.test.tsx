import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { resolveTheme, ThemeProvider, ThemeToggle } from "./theme";

describe("resolveTheme", () => {
  it.each([
    ["light", false, "light"],
    ["dark", false, "dark"],
    ["system", true, "dark"],
    ["system", false, "light"],
  ] as const)("%s (prefersDark=%s) → %s", (pref, prefersDark, expected) => {
    expect(resolveTheme(pref, prefersDark)).toBe(expected);
  });
});

describe("ThemeToggle", () => {
  it("cycles system → light → dark → system and persists", async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    const html = document.documentElement;
    expect(html.dataset.theme).toBe("light"); // system with matchMedia=false
    await user.click(screen.getByRole("button", { name: /^Theme: system/ }));
    expect(html.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("sb-theme")).toBe("light");
    await user.click(screen.getByRole("button", { name: /^Theme: light/ }));
    expect(html.dataset.theme).toBe("dark");
    await user.click(screen.getByRole("button", { name: /^Theme: dark/ }));
    expect(screen.getByRole("button", { name: /^Theme: system/ })).toBeInTheDocument();
  });

  it("survives a throwing localStorage", async () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    await user.click(screen.getByRole("button", { name: /^Theme: system/ }));
    expect(document.documentElement.dataset.theme).toBe("light");
    getItem.mockRestore();
    setItem.mockRestore();
  });
});
