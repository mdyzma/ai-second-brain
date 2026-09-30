import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { badgeFor, bannersFor, retryMessage, scanMessage } from "./labels";
import { SourcesScreen } from "./SourcesScreen";
import type { SourceRow, SourcesSummary } from "./types";

const BASE: SourcesSummary = {
  vault: { configured: true, readable: true },
  sources: { active: 3, deleted: 0 },
  revisions: { pending: 1, indexed: 1, failed: 1 },
  chunks: 10,
  embedding: { model: "bge-m3", embedded: 9, total: 10, host_reachable: true, last_error: null },
  jobs: { waiting: 1, failed: 0 },
  last_run: {
    trigger: "schedule",
    started_at: "2026-09-30T10:00:00Z",
    finished_at: "2026-09-30T10:00:02Z",
    outcome: "ok",
    counts: { changed: 3 },
  },
};
const row = (over: Partial<SourceRow>): SourceRow => ({
  id: crypto.randomUUID(),
  title: "NAS",
  path: "Projects/NAS.md",
  state: "indexed",
  error: null,
  indexed_at: "2026-09-30T10:00:00Z",
  chunks: 2,
  embedded: 2,
  ...over,
});

describe("labels", () => {
  it("maps rows to badges", () => {
    expect(badgeFor(row({})).label).toBe("Searchable");
    expect(badgeFor(row({ embedded: 1 })).label).toBe("Text only");
    expect(badgeFor(row({ state: "pending" })).label).toBe("Waiting");
    expect(badgeFor(row({ state: "failed", error: "too_large" })).label).toBe("Failed · too_large");
    expect(badgeFor(row({ state: "deleted" })).label).toBe("Deleted");
    expect(badgeFor(row({ chunks: 0, embedded: 0 })).label).toBe("Searchable");
  });

  it("builds banners in words", () => {
    expect(bannersFor({ ...BASE, vault: { configured: false, readable: false } })).toEqual([
      "No vault configured. Set SB_VAULT_PATH to your Obsidian vault and restart the worker.",
    ]);
    expect(bannersFor({ ...BASE, vault: { configured: true, readable: false } })).toContain(
      "The vault folder can't be read. Nothing was deleted.",
    );
    const tripped = {
      ...BASE,
      last_run: {
        ...(BASE.last_run as NonNullable<SourcesSummary["last_run"]>),
        outcome: "guard_tripped",
        counts: { tombstoned: 0, missing: 12 },
      },
    };
    expect(bannersFor(tripped)[0]).toMatch(
      /^The last scan found 12 notes missing and deleted nothing\./,
    );
    expect(
      bannersFor({ ...BASE, embedding: { ...BASE.embedding, last_error: "embed_model_missing" } }),
    ).toContain(
      "The embedding model isn't installed. Run `ollama pull bge-m3` on the embedding host.",
    );
    expect(
      bannersFor({ ...BASE, embedding: { ...BASE.embedding, host_reachable: false } }),
    ).toContain(
      "The embedding host is unreachable. Notes stay searchable by text; vectors are added when it's back.",
    );
  });
});

describe("action messages", () => {
  it("maps retry statuses to calm messages", () => {
    expect(retryMessage(409)).toBe("There is nothing to retry for this note.");
    expect(retryMessage(404)).toBe("That note is no longer in the index.");
    expect(retryMessage(503)).toBe("The database is unavailable. Try again in a moment.");
    expect(retryMessage(0)).toBe("Can't reach the server.");
    expect(retryMessage(500)).toBe("Couldn't queue the retry. Try again.");
  });

  it("maps scan statuses to calm messages", () => {
    expect(scanMessage(409)).toBe("No vault is configured, so there is nothing to scan.");
    expect(scanMessage(503)).toBe("The database is unavailable. Try again in a moment.");
    expect(scanMessage(0)).toBe("Can't reach the server.");
    expect(scanMessage(500)).toBe("Couldn't start the scan. Try again.");
  });
});

describe("SourcesScreen", () => {
  function renderScreen(overrides: Partial<Parameters<typeof SourcesScreen>[0]> = {}) {
    const props = {
      summary: BASE,
      rows: [
        row({}),
        row({
          path: "big.md",
          title: "big",
          state: "failed",
          error: "too_large",
          chunks: 0,
          embedded: 0,
        }),
      ],
      hasMore: false,
      scanPending: false,
      onRetry: vi.fn(async () => {}),
      onScan: vi.fn(async () => {}),
      onFilter: vi.fn(),
      onLoadMore: vi.fn(),
      ...overrides,
    };
    render(<SourcesScreen {...props} />);
    return props;
  }

  it("shows summary cards and the table", () => {
    renderScreen();
    expect(screen.getByText("Embedded 90%")).toBeInTheDocument();
    expect(screen.getByText("9 of 10 chunks")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Projects/NAS.md")).toBeInTheDocument();
    expect(within(table).getByText("Failed · too_large")).toBeInTheDocument();
  });

  it("retries failed rows and scans", async () => {
    const props = renderScreen();
    await userEvent.click(screen.getByRole("button", { name: "Retry big" }));
    expect(props.onRetry).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole("button", { name: "Scan now" }));
    expect(props.onScan).toHaveBeenCalledOnce();
  });

  it("disables scanning while queued and filters by state", async () => {
    const props = renderScreen({ scanPending: true });
    expect(screen.getByRole("button", { name: "Scan queued…" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Failed" }));
    expect(props.onFilter).toHaveBeenCalledWith({ state: "failed", q: "" });
  });

  it("retries with the row, and disables Retry while in flight", async () => {
    let finish: () => void = () => {};
    const onRetry = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    renderScreen({ onRetry });
    const button = screen.getByRole("button", { name: "Retry big" });
    await userEvent.click(button);
    expect(onRetry).toHaveBeenCalledWith(expect.objectContaining({ path: "big.md" }));
    expect(button).toBeDisabled();
    finish();
    await waitFor(() => expect(button).toBeEnabled());
  });

  it("passes the text filter and marks the active chip", async () => {
    const props = renderScreen();
    await userEvent.type(screen.getByPlaceholderText("Filter by title or path"), "nas");
    expect(props.onFilter).toHaveBeenLastCalledWith({ state: null, q: "nas" });
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Failed" }));
    expect(screen.getByRole("button", { name: "Failed" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "false");
  });

  it("renders the last scan card", () => {
    renderScreen();
    expect(screen.getByText("Last scan")).toBeInTheDocument();
    expect(screen.getByText("3 changed")).toBeInTheDocument();
    cleanup();
    renderScreen({ summary: { ...BASE, last_run: null } });
    expect(screen.getByText("never")).toBeInTheDocument();
  });

  it("loads more, and disables the button while loading", async () => {
    const props = renderScreen({ hasMore: true });
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(props.onLoadMore).toHaveBeenCalledOnce();
    cleanup();
    renderScreen({ hasMore: true, loadingMore: true });
    expect(screen.getByRole("button", { name: "Load more" })).toBeDisabled();
  });

  it("shows an empty state and a refresh note", () => {
    renderScreen({ rows: [], refreshNote: "Couldn't refresh. Showing the last known state." });
    expect(screen.getByText("No notes here yet.")).toBeInTheDocument();
    expect(screen.getByText("Couldn't refresh. Showing the last known state.")).toBeInTheDocument();
  });

  it("shows an inline notice and a list error", () => {
    renderScreen({ notice: "There is nothing to retry for this note.", listError: true });
    expect(screen.getByText("There is nothing to retry for this note.")).toBeInTheDocument();
    expect(screen.getByText("Couldn't load the list.")).toBeInTheDocument();
  });
});
