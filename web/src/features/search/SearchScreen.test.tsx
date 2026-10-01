import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SearchScreen } from "./SearchScreen";
import type { SearchFacets, SearchHit, SearchResponse } from "./types";
import type { SearchState } from "./url";

const hit = (over: Partial<SearchHit> = {}): SearchHit => ({
  source_id: "00000000-0000-0000-0000-000000000001",
  path: "Projects/NAS.md",
  title: "NAS",
  heading_path: ["Dyski"],
  snippet: "Cztery <mark>dyski</mark>",
  matched: ["text", "vector"],
  score: 0.03,
  obsidian_url: "obsidian://open?vault=Brain&file=Projects%2FNAS.md",
  ...over,
});

const FACETS: SearchFacets = {
  folders: [{ path: "Projects", count: 3 }],
  tags: [
    { tag: "homelab", count: 2 },
    { tag: "nas", count: 1 },
  ],
};

function setup(
  over: Partial<{
    state: SearchState;
    response: SearchResponse;
    loading: boolean;
    error: number;
    errorDetail: string;
    recent: string[];
  }> = {},
) {
  const props = {
    state: { q: "", tags: [] } as SearchState,
    onState: vi.fn(),
    facets: FACETS,
    loading: false,
    recent: [] as string[],
    onClearRecent: vi.fn(),
    ...over,
  };
  render(<SearchScreen {...props} />);
  return props;
}

const two: SearchResponse = {
  vector: "ok",
  results: [
    hit(),
    hit({ source_id: "00000000-0000-0000-0000-000000000002", path: "b.md", title: "Second" }),
  ],
};

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("SearchScreen", () => {
  it("shows the hint and recent queries; Clear calls onClearRecent", async () => {
    const props = setup({ recent: ["nas", "backup"] });
    expect(screen.getByText(/Type at least 2 characters/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "backup" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(props.onClearRecent).toHaveBeenCalledOnce();
  });

  it("debounces typing at 250 ms and Enter commits immediately", () => {
    vi.useFakeTimers();
    const props = setup();
    const input = screen.getByLabelText("Search your notes");
    fireEvent.change(input, { target: { value: "nas" } });
    act(() => {
      vi.advanceTimersByTime(249);
    });
    expect(props.onState).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(props.onState).toHaveBeenCalledWith({ q: "nas", tags: [] });

    props.onState.mockClear();
    fireEvent.change(input, { target: { value: "disks" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(props.onState).toHaveBeenCalledWith({ q: "disks", tags: [] });
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(props.onState).toHaveBeenCalledOnce();
  });

  it("renders a result with link, path, trail, mark and badges", () => {
    setup({ state: { q: "dyski", tags: [] }, response: two });
    const list = screen.getByRole("list", { name: "Search results" });
    const first = within(list).getAllByRole("listitem")[0] as HTMLElement;
    expect(within(first).getByRole("link", { name: "NAS" })).toHaveAttribute(
      "href",
      "obsidian://open?vault=Brain&file=Projects%2FNAS.md",
    );
    expect(within(first).getByText("Projects/NAS.md")).toBeInTheDocument();
    expect(within(first).getByText("NAS › Dyski")).toBeInTheDocument();
    expect(within(first).getByText("dyski").tagName).toBe("MARK");
    expect(within(first).getByText("Text")).toBeInTheDocument();
    expect(within(first).getByText("Meaning")).toBeInTheDocument();
  });

  it("explains when meaning search is unavailable", () => {
    setup({ state: { q: "nas", tags: [] }, response: { ...two, vector: "unavailable" } });
    expect(
      screen.getByText("Matching by meaning is unavailable right now; showing exact text matches."),
    ).toBeInTheDocument();
  });

  it("says nothing matched, and suggests clearing filters when some are set", () => {
    setup({
      state: { q: "zzz", folder: "Projects", tags: [] },
      response: { vector: "ok", results: [] },
    });
    expect(screen.getByText("No notes match. Try clearing the filters.")).toBeInTheDocument();
  });

  it("omits the filter hint when none are set", () => {
    setup({ state: { q: "zzz", tags: [] }, response: { vector: "ok", results: [] } });
    expect(screen.getByText("No notes match.")).toBeInTheDocument();
  });

  it("toggles tag chips and clears filters", async () => {
    const props = setup({
      state: { q: "nas", folder: "Projects", tags: ["nas"] },
      response: two,
    });
    expect(screen.getByRole("button", { name: "nas" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "homelab" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await userEvent.click(screen.getByRole("button", { name: "homelab" }));
    expect(props.onState).toHaveBeenLastCalledWith({
      q: "nas",
      folder: "Projects",
      tags: ["nas", "homelab"],
    });
    await userEvent.click(screen.getByRole("button", { name: "nas" }));
    expect(props.onState).toHaveBeenLastCalledWith({ q: "nas", folder: "Projects", tags: [] });
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(props.onState).toHaveBeenLastCalledWith({ q: "nas", tags: [] });
  });

  it("changes the folder", async () => {
    const props = setup({ state: { q: "nas", tags: [] }, response: two });
    await userEvent.selectOptions(screen.getByLabelText("Folder"), "Projects");
    expect(props.onState).toHaveBeenCalledWith({ q: "nas", tags: [], folder: "Projects" });
  });

  it("moves focus between result links with the arrow keys", async () => {
    setup({ state: { q: "nas", tags: [] }, response: two });
    const [a, b] = screen.getAllByRole("link");
    (a as HTMLElement).focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(b).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}");
    expect(a).toHaveFocus();
    screen.getByLabelText("Search your notes").focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(a).toHaveFocus();
  });

  it("announces the result count", () => {
    setup({ state: { q: "nas", tags: [] }, response: two });
    expect(screen.getByRole("status")).toHaveTextContent("2 results");
  });

  it("renders snippet HTML as text, never as elements", () => {
    const { container } = render(
      <SearchScreen
        state={{ q: "xx", tags: [] }}
        onState={vi.fn()}
        loading={false}
        recent={[]}
        onClearRecent={vi.fn()}
        response={{
          vector: "ok",
          results: [hit({ snippet: "&lt;script&gt;alert(1)&lt;/script&gt; <mark>x</mark>" })],
        }}
      />,
    );
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
  });

  it("focuses the input on / unless typing in a field", async () => {
    setup();
    const input = screen.getByLabelText("Search your notes");
    (document.body as HTMLElement).focus();
    input.blur();
    await userEvent.keyboard("/");
    expect(input).toHaveFocus();
    expect(input).toHaveValue("");
    const folder = screen.getByLabelText("Folder");
    folder.focus();
    await userEvent.keyboard("/");
    expect(folder).toHaveFocus();
  });

  it("shows error copy from the shared labels", () => {
    setup({ state: { q: "nas", tags: [] }, error: 409, errorDetail: "vault_disabled" });
    expect(screen.getByRole("alert")).toHaveTextContent("Set SB_VAULT_PATH to search your notes.");
  });

  it("marks the list busy while refreshing", () => {
    setup({ state: { q: "nas", tags: [] }, response: two, loading: true });
    const list = screen.getByRole("list", { name: "Search results" });
    expect(list).toHaveAttribute("aria-busy", "true");
    expect(list.className).toContain("opacity-60");
  });
});
