import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { EntityScreen } from "./EntityScreen";
import type { EntityDetail } from "./types";

const ref = (id: string, name: string, type: EntityDetail["type"] = "tool") => ({
  id,
  name,
  type,
});

const DETAIL: EntityDetail = {
  id: "e1",
  name: "Proxmox",
  type: "tool",
  status: "accepted",
  aliases: ["PVE", "Proxmox VE"],
  parent: ref("p1", "Homelab", "project"),
  children: [ref("c1", "LXC")],
  related: [
    { relation: "runs_on", direction: "out", entity: ref("d1", "NAS", "device") },
    { relation: "runs_on", direction: "in", entity: ref("t1", "Docker") },
  ],
  notes: [
    {
      source_id: "s1",
      path: "Projects/NAS.md",
      title: "NAS build",
      summary: "How the NAS was built",
      heading: "Dyski",
      relation: "mentions",
      obsidian_url: "obsidian://open?vault=Brain&file=Projects%2FNAS.md",
    },
    {
      source_id: "s2",
      path: "evil.md",
      title: "Evil",
      summary: null,
      heading: null,
      relation: "mentions",
      obsidian_url: "javascript:alert(1)",
    },
  ],
};

async function setup(props: Parameters<typeof EntityScreen>[0]) {
  const root = createRootRoute({ component: () => <EntityScreen {...props} /> });
  const rest = ["/entities", "/entities/$entityId"].map((path) =>
    createRoute({ getParentRoute: () => root, path, component: () => null }),
  );
  const router = createRouter({
    routeTree: root.addChildren(rest),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  render(<RouterProvider router={router} />);
}

afterEach(cleanup);

describe("EntityScreen", () => {
  it("shows the header with type and aliases", async () => {
    await setup({ entity: DETAIL, error: null });
    expect(await screen.findByRole("heading", { name: "Proxmox" })).toBeInTheDocument();
    expect(screen.getByText("Tool")).toBeInTheDocument();
    expect(screen.getByText(/PVE, Proxmox VE/)).toBeInTheDocument();
  });

  it("links the parent and lists children", async () => {
    await setup({ entity: DETAIL, error: null });
    expect(await screen.findByRole("link", { name: "Homelab" })).toHaveAttribute(
      "href",
      "/entities/p1",
    );
    expect(screen.getByRole("link", { name: "LXC" })).toHaveAttribute("href", "/entities/c1");
  });

  it("words related entities by direction", async () => {
    await setup({ entity: DETAIL, error: null });
    const out = (await screen.findByRole("link", { name: "NAS" })).closest("li");
    expect(out).toHaveTextContent("Runs on: NAS");
    const incoming = screen.getByRole("link", { name: "Docker" }).closest("li");
    expect(incoming).toHaveTextContent("Runs: Docker");
  });

  it("links notes only for obsidian urls and shows path, summary and heading", async () => {
    await setup({ entity: DETAIL, error: null });
    const link = await screen.findByRole("link", { name: "NAS build" });
    expect(link).toHaveAttribute("href", expect.stringMatching(/^obsidian:\/\//));
    expect(screen.getByText("Projects/NAS.md")).toBeInTheDocument();
    expect(screen.getByText("How the NAS was built")).toBeInTheDocument();
    expect(screen.getByText("Dyski")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Evil" })).toBeNull();
    expect(screen.getByText("Evil")).toBeInTheDocument();
  });

  it("explains a 404 and links back to the list", async () => {
    await setup({ error: 404 });
    expect(
      await screen.findByText("This entity no longer exists (it may have been merged)."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /entities/i })).toHaveAttribute("href", "/entities");
  });
});
