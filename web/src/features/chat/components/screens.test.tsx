import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { startTurn, turnReducer } from "../turn";
import type { ChatSession, ChatStatus, SessionDetail } from "../types";
import { Conversation } from "./Conversation";
import { NewSession } from "./NewSession";
import { SessionList } from "./SessionList";

const UP: ChatStatus = {
  private: {
    available: true,
    endpoints: [{ label: "gpu", model: "big", degraded: false, reachable: true }],
  },
  cloud: { available: true, model: "claude" },
};
const DOWN: ChatStatus = {
  private: { available: false, endpoints: [] },
  cloud: { available: false, model: null },
};
const SESSION: ChatSession = {
  id: "11111111-1111-4111-8111-111111111111",
  mode: "private",
  title: "Backups",
  created_at: "2026-09-29T10:00:00Z",
  updated_at: "2026-09-29T10:05:00Z",
};
const DETAIL: SessionDetail = {
  ...SESSION,
  turns: [
    {
      id: "22222222-2222-4222-8222-222222222222",
      seq: 1,
      question: "When do backups run?",
      answer: "Nightly [1].",
      sources: [
        { n: 1, source_id: "a", path: "notes/nas.md", heading: null, score: 0.9, snippet: "02:00" },
      ],
      endpoint: "gpu",
      model: "big",
      degraded: false,
      started_at: "2026-09-29T10:00:00Z",
      finished_at: "2026-09-29T10:00:05Z",
    },
  ],
};

describe("SessionList", () => {
  it("lists conversations and deletes after confirmation", async () => {
    const onDelete = vi.fn(async () => {});
    render(
      <SessionList
        sessions={[SESSION, { ...SESSION, id: "3", title: null, mode: "cloud" }]}
        activeId={SESSION.id}
        onDelete={onDelete}
        renderLink={(session, className) => (
          <a href={`#${session.id}`} className={className}>
            {session.title ?? "New conversation"}
          </a>
        )}
      />,
    );
    const nav = screen.getByRole("navigation", { name: "Conversations" });
    expect(within(nav).getByText("Backups")).toBeInTheDocument();
    expect(within(nav).getByText("New conversation")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete conversation: Backups" }));
    expect(screen.getByText("Delete this conversation?")).toBeInTheDocument();
    expect(screen.getByText("This cannot be undone.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalledWith(SESSION.id);
  });

  it("says when there are none", () => {
    render(<SessionList sessions={[]} onDelete={vi.fn()} renderLink={() => null} />);
    expect(screen.getByText("No conversations yet.")).toBeInTheDocument();
  });
});

describe("NewSession", () => {
  it("starts a private conversation by default", async () => {
    const onStart = vi.fn(async () => null);
    render(<NewSession status={UP} onStart={onStart} />);
    await userEvent.type(screen.getByLabelText("Ask privately"), "Hello?{Enter}");
    expect(onStart).toHaveBeenCalledWith("private", "Hello?");
  });

  it("switches the composer label for cloud and shows start errors", async () => {
    const onStart = vi.fn(async () => "Cloud mode is not configured.");
    render(<NewSession status={UP} onStart={onStart} />);
    await userEvent.click(screen.getByRole("radio", { name: /Cloud/ }));
    await userEvent.type(screen.getByLabelText("Ask cloud"), "Hi{Enter}");
    expect(onStart).toHaveBeenCalledWith("cloud", "Hi");
    expect(await screen.findByRole("alert")).toHaveTextContent("Cloud mode is not configured.");
  });

  it("disables private asking when no local model is reachable", () => {
    render(<NewSession status={DOWN} onStart={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("No local model reachable.");
    expect(screen.getByLabelText("Ask privately")).toBeDisabled();
    expect(
      screen.getByText("No local model reachable.", { selector: "p[id]" }),
    ).toBeInTheDocument();
  });
});

describe("Conversation", () => {
  it("shows saved turns with their sources and tier", () => {
    render(
      <Conversation
        session={DETAIL}
        status={UP}
        turn={null}
        busy={false}
        onSend={vi.fn()}
        onStop={vi.fn()}
      />,
    );
    expect(screen.getByRole("heading", { name: "Backups" })).toBeInTheDocument();
    expect(screen.getByText("notes/nas.md")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "[1]" })).toHaveAttribute("href", "#turn-1-source-1");
    expect(screen.getAllByText("Private · gpu (big)").length).toBeGreaterThan(0);
  });

  it("renders the in-flight turn after the saved ones and offers Stop", async () => {
    let turn = startTurn("And now?");
    turn = turnReducer(turn, {
      type: "event",
      event: { event: "sources", items: [], disabled: false },
    });
    turn = turnReducer(turn, { type: "event", event: { event: "token", text: "Partial" } });
    const onStop = vi.fn();
    render(
      <Conversation
        session={DETAIL}
        status={UP}
        turn={turn}
        busy
        onSend={vi.fn()}
        onStop={onStop}
      />,
    );
    const items = screen
      .getAllByRole("listitem")
      .filter((li) => li.closest("[aria-label='Conversation']"));
    expect(items.at(-1)).toHaveTextContent("And now?");
    expect(items.at(-1)).toHaveTextContent("Partial");
    await userEvent.click(screen.getByRole("button", { name: "Stop generating" }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("labels a cloud conversation and its composer", () => {
    render(
      <Conversation
        session={{ ...DETAIL, mode: "cloud", turns: [] }}
        status={UP}
        turn={null}
        busy={false}
        onSend={vi.fn()}
        onStop={vi.fn()}
      />,
    );
    expect(screen.getByText("Cloud · Anthropic — messages leave your network")).toBeInTheDocument();
    expect(screen.getByLabelText("Ask cloud")).toBeEnabled();
  });
});
