import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EntitiesScreen, type EntitiesScreenProps } from "./EntitiesScreen";
import type { EntitiesState } from "./entityUrl";
import type { EntitySummary } from "./types";

const ITEMS: EntitySummary[] = [
  { id: "e1", name: "Proxmox", type: "tool", note_count: 3 },
  { id: "e2", name: "NAS", type: "device", note_count: 1 },
];

async function setup(over: Partial<EntitiesScreenProps> = {}, initial: EntitiesState = { q: "" }) {
  const onState = vi.fn();
  function Host() {
    const [state, setState] = useState(initial);
    return (
      <EntitiesScreen
        state={state}
        onState={(next, change) => {
          onState(next, change);
          setState(next);
        }}
        items={ITEMS}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={vi.fn()}
        {...over}
      />
    );
  }
  const root = createRootRoute({ component: Host });
  const rest = ["/review", "/entities/$entityId"].map((path) =>
    createRoute({ getParentRoute: () => root, path, component: () => null }),
  );
  const router = createRouter({
    routeTree: root.addChildren(rest),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  render(<RouterProvider router={router} />);
  await screen.findByRole("heading", { name: "Entities" });
  return onState;
}

afterEach(cleanup);

describe("EntitiesScreen", () => {
  it("lists rows with name, type, note count and a link", async () => {
    await setup();
    const link = screen.getByRole("link", { name: /Proxmox/ });
    expect(link).toHaveAttribute("href", "/entities/e1");
    expect(within(link).getByText("Tool")).toBeInTheDocument();
    expect(within(link).getByText("3 notes")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /NAS/ })).toHaveTextContent("1 note");
  });

  it("marks the active type tab and commits a type change", async () => {
    const onState = await setup({}, { type: "tool", q: "" });
    expect(screen.getByRole("tablist", { name: "Entity type" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Tool" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "All" })).toHaveAttribute("aria-selected", "false");
    await userEvent.click(screen.getByRole("tab", { name: "Device" }));
    expect(onState).toHaveBeenCalledWith({ type: "device", q: "" }, "commit");
  });

  it("debounces typing into a single state change", async () => {
    const onState = await setup({}, { type: "tool", q: "" });
    const box = screen.getByRole("searchbox", { name: "Search entities" });
    await userEvent.type(box, "prox");
    expect(onState).not.toHaveBeenCalled();
    await waitFor(() => expect(onState).toHaveBeenCalledTimes(1));
    expect(onState).toHaveBeenCalledWith({ type: "tool", q: "prox" }, "typing");
  });

  it("shows the empty state linking to Review", async () => {
    await setup({ items: [] });
    expect(screen.getByText(/No entities yet\. Run extraction from/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review" })).toHaveAttribute("href", "/review");
  });

  it("says nothing matches when filtered", async () => {
    await setup({ items: [] }, { q: "zzz" });
    expect(screen.getByText("No entities match.")).toBeInTheDocument();
  });
});
