import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";
import { ThemeProvider } from "./theme";

async function renderShell(onLogout: () => void) {
  const rootRoute = createRootRoute({
    component: () => (
      <ThemeProvider>
        <AppShell onLogout={onLogout}>
          <Outlet />
        </AppShell>
      </ThemeProvider>
    ),
  });
  const routes = ["ask", "search"].map((path) =>
    createRoute({
      getParentRoute: () => rootRoute,
      path: `/${path}`,
      component: () => <p>{path} screen</p>,
    }),
  );
  const router = createRouter({
    routeTree: rootRoute.addChildren(routes),
    history: createMemoryHistory({ initialEntries: ["/search"] }),
  });
  await router.load();
  render(<RouterProvider router={router} />);
}

describe("AppShell", () => {
  beforeEach(() => {
    // jsdom does not implement scrolling; the router calls it after navigation.
    vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders primary navigation with the active link marked", async () => {
    await renderShell(vi.fn());
    const [nav] = await screen.findAllByRole("navigation", { name: "Primary" });
    expect(nav).toBeDefined();
    const active = within(nav as HTMLElement).getByRole("link", { name: "Search" });
    expect(active).toHaveAttribute("aria-current", "page");
    expect(within(nav as HTMLElement).getByRole("link", { name: "Ask" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("calls onLogout from the Log out button", async () => {
    const onLogout = vi.fn();
    await renderShell(onLogout);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Log out" }));
    expect(onLogout).toHaveBeenCalledTimes(1);
  });
});
