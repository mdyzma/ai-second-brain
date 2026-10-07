import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { runLabel } from "./copy";
import type { Digest, NightlyRun, NightlyRunSummary } from "./types";

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ api: { GET: get, POST: post } }));

import { DigestScreen } from "./DigestScreen";

function run(over: Partial<NightlyRun> = {}): NightlyRun {
  return {
    id: "r1",
    run_date: "2026-10-07",
    trigger: "schedule",
    status: "complete",
    timed_out: false,
    unavailable: false,
    error: null,
    started_at: "2026-10-07T02:00:00Z",
    finished_at: "2026-10-07T03:00:00Z",
    window_start: "2026-10-06T02:00:00Z",
    queued_new: 8,
    queued_failed: 2,
    done: 10,
    ...over,
  };
}

function digest(over: Partial<Digest> = {}, runOver: Partial<NightlyRun> = {}): Digest {
  return {
    nightly_at: "02:00",
    nightly_enabled: true,
    nightly_max_hours: 8,
    run: run(runOver),
    review: {
      remaining: 3,
      open_total: 3,
      entities: {
        count: 2,
        by_type: { tool: 1, person: 1 },
        top: [
          {
            id: "e1",
            name: "Proxmox",
            type: "tool",
            confidence: 0.9,
            source_title: "Homelab",
            source_path: "notes/homelab.md",
          },
          {
            id: "e2",
            name: "Ada",
            type: "person",
            confidence: null,
            source_title: null,
            source_path: "notes/ada.md",
          },
        ],
      },
      links: {
        count: 1,
        top: [
          {
            id: "l1",
            kind: "relation",
            subject: "Home Assistant",
            relation: "runs_on",
            object: "Proxmox",
            confidence: 0.8,
          },
        ],
      },
    },
    failed: { count: 1, items: [{ path: "notes/broken.md", error: "parse_error" }] },
    indexed: { created: 4, changed: 2, deleted: 1, since_beginning: false },
    ...over,
  };
}

const RUNS = {
  runs: [
    {
      id: "r1",
      run_date: "2026-10-07",
      trigger: "schedule",
      status: "complete",
      remaining: 3,
      started_at: "2026-10-07T02:00:00Z",
    },
    {
      id: "r0",
      run_date: "2026-10-07",
      trigger: "manual",
      status: "complete",
      remaining: 0,
      started_at: "2026-10-07T01:00:00Z",
    },
    {
      id: "rr",
      run_date: "2026-10-06",
      trigger: "schedule",
      status: "complete",
      remaining: 0,
      started_at: "2026-10-06T02:00:00Z",
    },
  ],
};

function mockGet(latest: Digest, byRun: Record<string, Digest> = {}) {
  get.mockImplementation(
    async (path: string, opts?: { params?: { path?: { run_id?: string } } }) => {
      if (path === "/api/digest") return { data: latest, response: { status: 200 } };
      if (path === "/api/digest/run/{run_id}") {
        const d = byRun[opts?.params?.path?.run_id ?? ""];
        return d
          ? { data: d, response: { status: 200 } }
          : { data: undefined, response: { status: 404 } };
      }
      if (path === "/api/nightly/runs") return { data: RUNS, response: { status: 200 } };
      throw new Error(`unexpected ${path}`);
    },
  );
}

async function setup(initialRun?: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Host() {
    const [runId, setRunId] = useState<string | undefined>(initialRun);
    return <DigestScreen runId={runId} onRun={setRunId} />;
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
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { level: 1, name: "Digest" });
  return qc;
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
});

describe("DigestScreen", () => {
  it("shows the no-runs copy with the configured time", async () => {
    mockGet({
      nightly_at: "03:30",
      nightly_enabled: true,
      nightly_max_hours: 8,
      run: null,
      review: null,
      failed: null,
      indexed: null,
    });
    await setup();
    expect(
      await screen.findByText("No nightly run yet. The first starts at 03:30, or press Run now."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run now" })).toBeEnabled();
    expect(screen.queryByRole("region", { name: /To review/ })).not.toBeInTheDocument();
  });

  it("shows progress while running and disables Run now", async () => {
    mockGet(digest({}, { status: "running", done: 3, queued_new: 8, queued_failed: 2 }));
    await setup();
    const line = await screen.findByText("Reading notes: 3 of 10.");
    expect(line.closest("[aria-live='polite']")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Run now" })).toBeDisabled();
  });

  it("renders a complete run with its sections", async () => {
    mockGet(digest());
    await setup();
    expect(
      await screen.findByText("Last night: 10 notes read, 1 failed, 3 to review."),
    ).toBeInTheDocument();
    expect(screen.getByText("2026-10-07 · Scheduled run")).toBeInTheDocument();
    const review = screen.getByRole("region", { name: /^To review/ });
    expect(within(review).getByTestId("remaining")).toHaveTextContent("3");
    expect(within(review).getByText("Tool: 1")).toBeInTheDocument();
    expect(within(review).getByText("Person: 1")).toBeInTheDocument();
    expect(within(review).getByRole("link", { name: /Proxmox/ })).toHaveAttribute(
      "href",
      "/entities/e1",
    );
    expect(within(review).getByText("Home Assistant — runs on — Proxmox")).toBeInTheDocument();
    expect(within(review).getByRole("link", { name: "Review all" })).toHaveAttribute(
      "href",
      "/review",
    );
    expect(within(review).getByRole("link", { name: "Review links" })).toHaveAttribute(
      "href",
      "/review?tab=links",
    );
    const failed = screen.getByRole("region", { name: /^Failed/ });
    expect(within(failed).getByText("notes/broken.md").tagName).toBe("CODE");
    expect(within(failed).getByText("just graph-extract --failed").tagName).toBe("CODE");
    expect(
      screen.getByText("4 added, 2 changed, 1 deleted since the previous run"),
    ).toBeInTheDocument();
  });

  it("says since the beginning for the first run", async () => {
    mockGet(
      digest(
        { indexed: { created: 4, changed: 0, deleted: 0, since_beginning: true } },
        { window_start: null },
      ),
    );
    await setup();
    expect(
      await screen.findByText("4 added, 0 changed, 0 deleted since the beginning"),
    ).toBeInTheDocument();
  });

  it("says all caught up when nothing remains", async () => {
    mockGet(
      digest({
        review: {
          remaining: 0,
          open_total: 0,
          entities: { count: 0, by_type: {}, top: [] },
          links: { count: 0, top: [] },
        },
        failed: { count: 0, items: [] },
      }),
    );
    await setup();
    const review = await screen.findByRole("region", { name: /^To review/ });
    expect(within(review).getByText("All caught up.")).toBeInTheDocument();
    expect(within(review).getByTestId("remaining")).toHaveTextContent("0");
    expect(screen.queryByRole("region", { name: /^Failed/ })).not.toBeInTheDocument();
    expect(within(review).queryByText(/more waiting/)).not.toBeInTheDocument();
  });

  it("never says all caught up while earlier items wait", async () => {
    mockGet(
      digest({
        review: {
          remaining: 0,
          open_total: 18,
          entities: { count: 0, by_type: {}, top: [] },
          links: { count: 0, top: [] },
        },
      }),
    );
    await setup();
    const review = await screen.findByRole("region", { name: /^To review/ });
    expect(within(review).getByText("Nothing new from this run.")).toBeInTheDocument();
    expect(within(review).queryByText("All caught up.")).not.toBeInTheDocument();
    expect(
      within(review).getByRole("link", { name: "18 more waiting from earlier runs." }),
    ).toHaveAttribute("href", "/review");
  });

  it("lists this run's items and links to the rest", async () => {
    const base = digest();
    mockGet({ ...base, review: base.review && { ...base.review, open_total: 5 } });
    await setup();
    const review = await screen.findByRole("region", { name: /^To review/ });
    expect(within(review).getByTestId("remaining")).toHaveTextContent("3");
    expect(within(review).getByRole("link", { name: /Proxmox/ })).toBeInTheDocument();
    expect(
      within(review).getByRole("link", { name: "2 more waiting from earlier runs." }),
    ).toHaveAttribute("href", "/review");
  });

  it("explains an unavailable run", async () => {
    mockGet(digest({}, { unavailable: true }));
    await setup();
    expect(
      await screen.findByText(
        "Extraction is off: no Ollama endpoint is configured (SB_OLLAMA_ENDPOINTS).",
      ),
    ).toBeInTheDocument();
  });

  it("explains a timed-out run with the configured hours, not the elapsed time", async () => {
    mockGet(
      digest(
        { nightly_max_hours: 6 },
        {
          timed_out: true,
          // the machine slept: closed 16 hours after the start
          started_at: "2026-10-07T02:00:00Z",
          finished_at: "2026-10-07T18:05:00Z",
        },
      ),
    );
    await setup();
    expect(
      await screen.findByText(
        "Stopped waiting after 6 hours. Remaining notes will finish in the background.",
      ),
    ).toBeInTheDocument();
  });

  it("explains a run that failed to start", async () => {
    mockGet(
      digest(
        { review: null, failed: null, indexed: null },
        { status: "failed", error: "db_error" },
      ),
    );
    await setup();
    expect(
      await screen.findByText(
        "Last night's run failed to start (db_error). It will try again at the next check.",
      ),
    ).toBeInTheDocument();
  });

  it("posts Run now and shows the busy copy on 409", async () => {
    mockGet(digest());
    post.mockResolvedValueOnce({ data: { run: run() }, response: { status: 202 } });
    post.mockResolvedValueOnce({
      data: undefined,
      error: { detail: "nightly_busy" },
      response: { status: 409 },
    });
    await setup();
    const button = await screen.findByRole("button", { name: "Run now" });
    await waitFor(() => expect(button).toBeEnabled());
    const user = userEvent.setup();
    await user.click(button);
    expect(post).toHaveBeenCalledWith("/api/nightly/run");
    await waitFor(() => expect(button).toBeEnabled());
    expect(screen.queryByText("A run is already in progress.")).not.toBeInTheDocument();
    // Another process started a run: the 409 refreshes the digest, which now shows it.
    mockGet(digest({}, { status: "running", done: 1 }));
    await user.click(button);
    const busy = await screen.findByText("A run is already in progress.");
    expect(busy).toHaveAttribute("role", "status");
    expect(post).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Reading notes: 1 of 10.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("clears the busy line once the run ends", async () => {
    mockGet(digest());
    post.mockResolvedValue({
      data: undefined,
      error: { detail: "nightly_busy" },
      response: { status: 409 },
    });
    const qc = await setup();
    const button = await screen.findByRole("button", { name: "Run now" });
    await waitFor(() => expect(button).toBeEnabled());
    mockGet(digest({}, { status: "running", done: 1 }));
    await userEvent.setup().click(button);
    expect(await screen.findByText("A run is already in progress.")).toBeInTheDocument();
    mockGet(digest());
    await qc.invalidateQueries();
    await waitFor(() =>
      expect(screen.queryByText("A run is already in progress.")).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run now" })).toBeEnabled();
  });

  it("switches runs by id, also to an earlier run on the same date", async () => {
    const older = digest(
      {
        review: {
          remaining: 0,
          open_total: 3,
          entities: { count: 0, by_type: {}, top: [] },
          links: { count: 0, top: [] },
        },
      },
      { id: "r0", run_date: "2026-10-07", trigger: "manual", done: 5 },
    );
    mockGet(digest(), { r0: older });
    await setup();
    const picker = await screen.findByRole("combobox", { name: "Run" });
    const label = runLabel(RUNS.runs[1] as NightlyRunSummary);
    expect(label).toMatch(/^2026-10-07 \d\d:\d\d · Manual$/);
    await waitFor(() => expect(within(picker).getAllByRole("option")).toHaveLength(3));
    expect(within(picker).getByRole("option", { name: label })).toBeInTheDocument();
    await userEvent.setup().selectOptions(picker, "r0");
    expect(
      await screen.findByText("Last night: 5 notes read, 1 failed, 0 to review."),
    ).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/api/digest/run/{run_id}", {
      params: { path: { run_id: "r0" } },
    });
    expect(screen.getByRole("combobox", { name: "Run" })).toHaveValue("r0");
  });

  it("says when a linked run no longer exists", async () => {
    mockGet(digest());
    await setup("gone");
    expect(await screen.findByText("That run no longer exists.")).toBeInTheDocument();
  });

  it("shows the load error with a retry", async () => {
    get.mockResolvedValue({ data: undefined, response: { status: 500 } });
    await setup();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't load the digest. Try again.",
    );
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
