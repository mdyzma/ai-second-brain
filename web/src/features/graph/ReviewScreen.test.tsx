import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReviewScreen, type ReviewScreenProps } from "./ReviewScreen";
import type { GraphStatus, ReviewEntity, ReviewLink } from "./types";

const STATUS: GraphStatus = {
  available: true,
  model: "qwen",
  extractor_version: "4a.1",
  queued: 0,
  revisions: { total: 10, extracted: 7, failed: 1, pending: 2 },
  entities: {
    tool: { proposed: 2, accepted: 3, rejected: 1 },
    device: { proposed: 1, accepted: 0, rejected: 0 },
  },
};

const entity = (over: Partial<ReviewEntity> = {}): ReviewEntity => ({
  id: "e1",
  name: "Proxmox",
  type: "tool",
  aliases: [],
  mention_count: 3,
  samples: [
    {
      path: "Projects/NAS.md",
      title: "NAS",
      summary: "A homelab note",
      obsidian_url: "obsidian://open?vault=Brain&file=Projects%2FNAS.md",
    },
    { path: "evil.md", title: "Evil", summary: null, obsidian_url: "javascript:alert(1)" },
  ],
  suggestion: null,
  ...over,
});
const E1 = entity();
const E2 = entity({ id: "e2", name: "Docker", samples: [] });

const link = (over: Partial<ReviewLink> = {}): ReviewLink => ({
  id: "l1",
  kind: "relation",
  subject: { id: "e1", name: "Proxmox", type: "tool" },
  note: null,
  relation: "runs_on",
  object: { id: "e9", name: "NAS", type: "device" },
  confidence: 0.7,
  evidence: { path: "Projects/NAS.md", heading: "Dyski", obsidian_url: null },
  ...over,
});

const ok = { ok: true } as const;

function setup(over: Partial<ReviewScreenProps> = {}) {
  return setupWith(over).props;
}

function setupWith(over: Partial<ReviewScreenProps> = {}) {
  const props: ReviewScreenProps = {
    status: STATUS,
    entities: [E1, E2],
    entitiesLoading: false,
    entitiesError: null,
    hasMoreEntities: false,
    onLoadMoreEntities: vi.fn(),
    links: [],
    linksLoading: false,
    linksError: null,
    hasMoreLinks: false,
    onLoadMoreLinks: vi.fn(),
    onDecide: vi.fn(async () => ok),
    onDecideLinks: vi.fn(async () => ok),
    onRun: vi.fn(async () => ({ ok: true, queued: 4 }) as const),
    onSearch: vi.fn(async () => [
      { id: "t1", name: "Proxmox VE", type: "tool" as const, note_count: 5 },
    ]),
    ...over,
  };
  const view = render(<ReviewScreen {...props} />);
  return { props, view };
}

afterEach(cleanup);

describe("header", () => {
  it("shows counts and offers both extraction scopes", async () => {
    const props = setup();
    expect(screen.getByText("7 of 10")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run extraction" }));
    expect(screen.getByRole("menuitem", { name: "New notes" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("menuitem", { name: "Retry failed" }));
    expect(props.onRun).toHaveBeenCalledWith("failed");
    expect(await screen.findByRole("status")).toHaveTextContent("Queued 4 notes for extraction.");
  });

  it("uses the singular for one note", async () => {
    setup({ onRun: vi.fn(async () => ({ ok: true, queued: 1 }) as const) });
    await userEvent.click(screen.getByRole("button", { name: "Run extraction" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "New notes" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Queued 1 note for extraction.");
  });

  it("disables the menu when no model is available", () => {
    setup({ status: { ...STATUS, available: false } });
    expect(screen.getByRole("button", { name: "Run extraction" })).toBeDisabled();
    expect(screen.getByText("No local model is configured for extraction.")).toBeInTheDocument();
  });

  it("maps a failed run to calm copy", async () => {
    setup({
      onRun: vi.fn(
        async () => ({ ok: false, status: 409, detail: "extraction_unavailable" }) as const,
      ),
    });
    await userEvent.click(screen.getByRole("button", { name: "Run extraction" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "New notes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No local model is configured for extraction.",
    );
  });
});

describe("entities tab", () => {
  it("renders cards with samples, linking only obsidian urls", () => {
    setup({
      entities: [entity({ suggestion: { id: "t1", name: "Proxmox VE", similarity: 0.93 } }), E2],
    });
    expect(screen.getByRole("tab", { name: /Entities/ })).toHaveAttribute("aria-selected", "true");
    const card = screen.getByRole("article", { name: "Proxmox" });
    expect(within(card).getByLabelText("Name")).toHaveValue("Proxmox");
    expect(within(card).getByLabelText("Type")).toHaveValue("tool");
    expect(within(card).getByText("3 mentions")).toBeInTheDocument();
    expect(within(card).getByText("A homelab note")).toBeInTheDocument();
    expect(within(card).getAllByRole("link")).toHaveLength(1);
    expect(within(card).getByText(/Looks like Proxmox VE \(93% match\)/)).toBeInTheDocument();
  });

  it("accepts with a, moves focus to the next card, and rejects with r", async () => {
    const props = setup();
    const first = screen.getByRole("article", { name: "Proxmox" });
    first.focus();
    await userEvent.keyboard("a");
    expect(props.onDecide).toHaveBeenCalledWith("e1", { action: "accept" });
    await waitFor(() => expect(screen.getByRole("article", { name: "Docker" })).toHaveFocus());
    await userEvent.keyboard("r");
    expect(props.onDecide).toHaveBeenLastCalledWith("e2", { action: "reject" });
  });

  it("moves between cards with j and k", async () => {
    setup();
    screen.getByRole("article", { name: "Proxmox" }).focus();
    await userEvent.keyboard("j");
    expect(screen.getByRole("article", { name: "Docker" })).toHaveFocus();
    await userEvent.keyboard("k");
    expect(screen.getByRole("article", { name: "Proxmox" })).toHaveFocus();
  });

  it("ignores shortcuts while a modifier key is held", async () => {
    const props = setup();
    screen.getByRole("article", { name: "Proxmox" }).focus();
    await userEvent.keyboard("{Control>}a{/Control}");
    expect(props.onDecide).not.toHaveBeenCalled();
  });

  it("merges through the picker, searching the same type", async () => {
    const props = setup();
    screen.getByRole("article", { name: "Proxmox" }).focus();
    await userEvent.keyboard("m");
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(props.onSearch).toHaveBeenCalledWith("tool", ""));
    await userEvent.type(within(dialog).getByLabelText("Search entities"), "a");
    expect(props.onDecide).not.toHaveBeenCalled();
    await userEvent.click(await within(dialog).findByRole("button", { name: /Proxmox VE/ }));
    expect(props.onDecide).toHaveBeenCalledWith("e1", { action: "merge", into_id: "t1" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("does not fire shortcuts typed in the name input", async () => {
    const props = setup();
    const input = within(screen.getByRole("article", { name: "Proxmox" })).getByLabelText("Name");
    await userEvent.click(input);
    await userEvent.keyboard("arm");
    expect(props.onDecide).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renames on Enter and offers a merge on name_taken", async () => {
    const onDecide = vi.fn(async () => ({ ok: false, status: 409, detail: "name_taken" }) as const);
    setup({ onDecide });
    const card = screen.getByRole("article", { name: "Proxmox" });
    const input = within(card).getByLabelText("Name");
    await userEvent.clear(input);
    await userEvent.type(input, "Docker{Enter}");
    expect(onDecide).toHaveBeenCalledWith("e1", { action: "rename", name: "Docker" });
    expect(
      await within(card).findByText("Another tool already has this name — merge instead?"),
    ).toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button", { name: "Merge" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Merge Proxmox into…");
  });

  it("retypes from the select", async () => {
    const props = setup();
    const card = screen.getByRole("article", { name: "Proxmox" });
    await userEvent.selectOptions(within(card).getByLabelText("Type"), "device");
    expect(props.onDecide).toHaveBeenCalledWith("e1", { action: "retype", type: "device" });
  });

  it("sets a parent and maps parent_cycle", async () => {
    const onDecide = vi.fn(
      async () => ({ ok: false, status: 422, detail: "parent_cycle" }) as const,
    );
    const props = setup({ onDecide });
    await userEvent.click(
      within(screen.getByRole("article", { name: "Proxmox" })).getByRole("button", {
        name: "Set parent…",
      }),
    );
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(props.onSearch).toHaveBeenCalledWith("tool", ""));
    await userEvent.click(await within(dialog).findByRole("button", { name: /Proxmox VE/ }));
    expect(onDecide).toHaveBeenCalledWith("e1", { action: "parent", parent_id: "t1" });
    expect(await within(dialog).findByText("That would make a loop.")).toBeInTheDocument();
  });

  it("shows the empty, loading and error states without server text", () => {
    setup({ entities: [] });
    expect(screen.getByText("Nothing to review.")).toBeInTheDocument();
    cleanup();
    setup({ entities: [], entitiesLoading: true });
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    cleanup();
    setup({ entities: [], entitiesError: 503 });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The database is unavailable. Try again in a moment.",
    );
  });
});

describe("entities tab: fixes", () => {
  it("focuses the empty state after the last card is decided", async () => {
    const { props, view } = setupWith({ entities: [E1] });
    screen.getByRole("article", { name: "Proxmox" }).focus();
    await userEvent.keyboard("a");
    expect(props.onDecide).toHaveBeenCalledWith("e1", { action: "accept" });
    view.rerender(<ReviewScreen {...props} entities={[]} />);
    await waitFor(() => expect(screen.getByText("Nothing to review.")).toHaveFocus());
  });

  it("announces decisions politely", async () => {
    setup();
    screen.getByRole("article", { name: "Proxmox" }).focus();
    await userEvent.keyboard("a");
    await waitFor(() => expect(screen.getByText("Accepted Proxmox.")).toBeInTheDocument());
    expect(screen.getByText("Accepted Proxmox.")).toHaveAttribute("aria-live", "polite");
  });

  it("shows busy copy for a 409 busy", async () => {
    setup({ onDecide: vi.fn(async () => ({ ok: false, status: 409, detail: "busy" }) as const) });
    screen.getByRole("article", { name: "Proxmox" }).focus();
    await userEvent.keyboard("a");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Someone else is changing the graph right now. Try again.",
    );
  });

  it("blocks a rapid second action and says so", async () => {
    let release: (r: { ok: true }) => void = () => {};
    const onDecide = vi.fn(() => new Promise<{ ok: true }>((res) => (release = res)));
    setup({ onDecide });
    screen.getByRole("article", { name: "Proxmox" }).focus();
    await userEvent.keyboard("a");
    await userEvent.keyboard("r");
    expect(onDecide).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Still saving the last change. Try again in a moment.",
    );
    release({ ok: true });
  });

  it("ignores shortcuts while a dialog is open", async () => {
    const props = setup();
    await userEvent.click(
      within(screen.getByRole("article", { name: "Proxmox" })).getByRole("button", {
        name: "Merge into…",
      }),
    );
    const dialog = await screen.findByRole("dialog");
    fireEvent.keyDown(dialog, { key: "a" });
    fireEvent.keyDown(dialog, { key: "r" });
    expect(props.onDecide).not.toHaveBeenCalled();
  });

  it("shows a search error and ends loading when the picker search rejects", async () => {
    setup({ onSearch: vi.fn(async () => Promise.reject(new Error("boom"))) });
    await userEvent.click(
      within(screen.getByRole("article", { name: "Proxmox" })).getByRole("button", {
        name: "Merge into…",
      }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByText("Couldn't search entities. Try again."),
    ).toBeInTheDocument();
    expect(within(dialog).queryByText("Loading…")).not.toBeInTheDocument();
  });
});

describe("links tab", () => {
  const L2 = link({ id: "l2", object: { id: "e8", name: "Backup", type: "topic" } });

  async function openLinks(over: Partial<ReviewScreenProps> = {}) {
    const props = setup({ links: [link(), L2], ...over });
    await userEvent.click(screen.getByRole("tab", { name: /Links/ }));
    return props;
  }

  it("reads each row as a sentence with its evidence", async () => {
    await openLinks();
    expect(screen.getByRole("tab", { name: /Links/ })).toHaveAttribute("aria-selected", "true");
    const row = screen.getByLabelText("Select Proxmox runs on NAS").closest("li") as HTMLElement;
    expect(row).toHaveTextContent("Proxmox runs on NAS · Projects/NAS.md › Dyski");
  });

  it("batch-accepts the checked rows", async () => {
    const props = await openLinks();
    const accept = screen.getByRole("button", { name: "Accept selected" });
    expect(accept).toBeDisabled();
    await userEvent.click(screen.getByLabelText("Select Proxmox runs on NAS"));
    await userEvent.click(screen.getByLabelText("Select Proxmox runs on Backup"));
    await userEvent.click(accept);
    expect(props.onDecideLinks).toHaveBeenCalledWith([
      { id: "l1", decision: "accept" },
      { id: "l2", decision: "accept" },
    ]);
    await waitFor(() =>
      expect(screen.getByLabelText("Select Proxmox runs on NAS")).not.toBeChecked(),
    );
    expect(screen.getByLabelText("Select Proxmox runs on Backup")).not.toBeChecked();
  });

  it("rejects a single row", async () => {
    const props = await openLinks();
    await userEvent.click(screen.getByRole("button", { name: "Reject: Proxmox runs on NAS" }));
    expect(props.onDecideLinks).toHaveBeenCalledWith([{ id: "l1", decision: "reject" }]);
  });

  it("disables batch buttons above 100 selected", async () => {
    const many = Array.from({ length: 101 }, (_, i) =>
      link({ id: `l${i}`, object: { id: `o${i}`, name: `Obj${i}`, type: "device" } }),
    );
    await openLinks({ links: many });
    for (const box of screen.getAllByRole("checkbox")) await userEvent.click(box);
    expect(screen.getByRole("button", { name: "Accept selected" })).toBeDisabled();
    expect(screen.getByText("Select at most 100 at a time.")).toBeInTheDocument();
  }, 30_000);

  it("shows mapped copy when a batch fails", async () => {
    await openLinks({ onDecideLinks: vi.fn(async () => ({ ok: false, status: 409 }) as const) });
    await userEvent.click(screen.getByRole("button", { name: "Accept: Proxmox runs on NAS" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Someone else is changing the graph right now. Try again.",
    );
  });

  it("shows the empty state", async () => {
    await openLinks({ links: [] });
    expect(screen.getByText("Nothing to review.")).toBeInTheDocument();
  });
});
