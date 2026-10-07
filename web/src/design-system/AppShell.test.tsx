import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { captureNote } from "@/features/capture/api";
import { AppShell } from "./AppShell";
import { ThemeProvider } from "./theme";

vi.mock("@/features/capture/api", () => ({ captureNote: vi.fn() }));
const get = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ api: { GET: get, POST: vi.fn() } }));

function latestDigest(openTotal: number | null) {
  return {
    nightly_at: "02:00",
    nightly_enabled: true,
    run: openTotal === null ? null : { id: "r1", status: "complete" },
    review:
      openTotal === null
        ? null
        : {
            // The badge counts everything awaiting review, not just the latest run's.
            remaining: 0,
            open_total: openTotal,
            entities: { count: 0, by_type: {}, top: [] },
            links: { count: 0, top: [] },
          },
    failed: null,
    indexed: null,
  };
}

async function renderShell(onLogout: () => void, openTotal: number | null = null) {
  get.mockResolvedValue({ data: latestDigest(openTotal), response: { status: 200 } });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const rootRoute = createRootRoute({
    component: () => (
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <AppShell onLogout={onLogout}>
            <Outlet />
          </AppShell>
        </ThemeProvider>
      </QueryClientProvider>
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

  it("gives active and inactive links non-conflicting colour classes", async () => {
    await renderShell(vi.fn());
    const [nav] = await screen.findAllByRole("navigation", { name: "Primary" });
    const active = within(nav as HTMLElement).getByRole("link", { name: "Search" });
    const inactive = within(nav as HTMLElement).getByRole("link", { name: "Ask" });
    expect(active.className).toContain("text-accent-fg");
    expect(active.className).not.toContain("text-fg-muted");
    expect(inactive.className).toContain("text-fg-muted");
    expect(inactive.className).not.toContain("bg-accent");
  });

  describe("digest badge", () => {
    it("shows everything awaiting review on the Digest item only", async () => {
      await renderShell(vi.fn(), 3);
      expect(get).toHaveBeenCalledWith("/api/digest");
      const badged = await screen.findAllByRole("link", { name: "Digest 3 to review" });
      // Sidebar and phone bar.
      expect(badged).toHaveLength(2);
      for (const link of badged) {
        expect(within(link).getByText("3")).toBeInTheDocument();
        expect(within(link).getByText("to review")).toHaveClass("sr-only");
      }
      expect(screen.getAllByText(/to review/)).toHaveLength(2);
      expect(screen.getAllByRole("link", { name: "Review" })).toHaveLength(2);
    });

    it("shows no badge when nothing remains", async () => {
      await renderShell(vi.fn(), 0);
      const [nav] = await screen.findAllByRole("navigation", { name: "Primary" });
      await waitFor(() => expect(get).toHaveBeenCalled());
      expect(within(nav as HTMLElement).getByRole("link", { name: "Digest" })).toBeInTheDocument();
      expect(within(nav as HTMLElement).queryByText(/to review/)).not.toBeInTheDocument();
    });
  });

  describe("capture", () => {
    it("opens from the Capture button", async () => {
      await renderShell(vi.fn());
      await userEvent.setup().click(await screen.findByRole("button", { name: "Capture" }));
      expect(await screen.findByRole("textbox", { name: "Note" })).toBeInTheDocument();
    });

    it("opens on c from the page body", async () => {
      await renderShell(vi.fn());
      await screen.findAllByRole("navigation", { name: "Primary" });
      await userEvent.setup().keyboard("c");
      expect(await screen.findByRole("textbox", { name: "Note" })).toBeInTheDocument();
    });

    it("ignores c when composing or already handled", async () => {
      await renderShell(vi.fn());
      await screen.findAllByRole("navigation", { name: "Primary" });
      fireEvent.keyDown(document.body, { key: "c", isComposing: true });
      const handled = (e: KeyboardEvent) => e.preventDefault();
      document.addEventListener("keydown", handled, true);
      fireEvent.keyDown(document.body, { key: "c" });
      document.removeEventListener("keydown", handled, true);
      expect(screen.queryByRole("textbox", { name: "Note" })).not.toBeInTheDocument();
    });

    it("ignores c inside a field, with a modifier, or while open", async () => {
      await renderShell(vi.fn());
      await screen.findAllByRole("navigation", { name: "Primary" });
      const input = document.createElement("input");
      document.body.append(input);
      const user = userEvent.setup();
      input.focus();
      await user.keyboard("c");
      input.blur();
      await user.keyboard("{Control>}c{/Control}");
      input.remove();
      expect(screen.queryByRole("textbox", { name: "Note" })).not.toBeInTheDocument();
      await user.keyboard("c");
      const box = await screen.findByRole("textbox", { name: "Note" });
      await user.type(box, "c");
      expect(box).toHaveValue("c");
    });

    it("shows the saved status with an Obsidian link, then clears it after 6 s", async () => {
      vi.mocked(captureNote).mockResolvedValue({
        ok: true,
        path: "Inbox/x.md",
        title: "x",
        obsidian_url: "obsidian://open?vault=B&file=x",
      });
      localStorage.clear();
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        await renderShell(vi.fn());
        const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
        await user.click(await screen.findByRole("button", { name: "Capture" }));
        await user.type(await screen.findByRole("textbox", { name: "Note" }), "hi");
        await user.click(screen.getByRole("button", { name: "Save" }));
        const status = await screen.findByRole("status");
        expect(await within(status).findByText("Saved to Inbox")).toBeInTheDocument();
        expect(within(status).getByRole("link", { name: "Open in Obsidian" })).toHaveAttribute(
          "href",
          "obsidian://open?vault=B&file=x",
        );
        act(() => {
          vi.advanceTimersByTime(5000);
        });
        expect(within(status).getByText("Saved to Inbox")).toBeInTheDocument();
        act(() => {
          vi.advanceTimersByTime(1500);
        });
        expect(within(status).queryByText("Saved to Inbox")).not.toBeInTheDocument();
      } finally {
        vi.useRealTimers();
      }
    });

    it("omits the link for a non-obsidian URL", async () => {
      vi.mocked(captureNote).mockResolvedValue({
        ok: true,
        path: "Inbox/x.md",
        title: "x",
        obsidian_url: "javascript:alert(1)",
      });
      await renderShell(vi.fn());
      const user = userEvent.setup();
      await user.click(await screen.findByRole("button", { name: "Capture" }));
      await user.type(await screen.findByRole("textbox", { name: "Note" }), "hi");
      await user.click(screen.getByRole("button", { name: "Save" }));
      const status = await screen.findByRole("status");
      expect(await within(status).findByText("Saved to Inbox")).toBeInTheDocument();
      expect(within(status).queryByRole("link")).not.toBeInTheDocument();
    });
  });
});
