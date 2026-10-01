import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CaptureDialog } from "./CaptureDialog";

vi.mock("./api", () => ({ captureNote: vi.fn() }));

import { captureNote } from "./api";

const mocked = vi.mocked(captureNote);
const KEY = "sb.capture.draft";

function Harness({ onSaved }: { onSaved?: () => void }) {
  return <CaptureDialog open onOpenChange={vi.fn()} {...(onSaved ? { onSaved } : {})} />;
}

describe("CaptureDialog", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.resetAllMocks());

  it("posts on Ctrl+Enter, reports success, closes and clears the draft", async () => {
    const result = {
      ok: true as const,
      path: "Inbox/x.md",
      title: "x",
      obsidian_url: "obsidian://open?vault=B&file=x",
    };
    mocked.mockResolvedValue(result);
    const onOpenChange = vi.fn();
    const onSaved = vi.fn();
    render(<CaptureDialog open onOpenChange={onOpenChange} onSaved={onSaved} />);
    await userEvent.type(screen.getByRole("textbox", { name: "Note" }), "hello");
    expect(localStorage.getItem(KEY)).toBe("hello");
    await userEvent.keyboard("{Control>}{Enter}{/Control}");
    expect(mocked).toHaveBeenCalledWith("hello");
    expect(onSaved).toHaveBeenCalledWith(result);
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("disables Save while the text is empty", () => {
    render(<Harness />);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it.each([
    [503, "vault_unwritable", "Couldn't write to the vault folder."],
    [409, "vault_disabled", "No vault is configured. Set SB_VAULT_PATH."],
    [409, "capture_name_taken", "Too many captures with this title this minute."],
    [0, undefined, "Can't reach the server."],
    [500, undefined, "Couldn't save the note. Try again."],
  ])("maps %s %s to copy and keeps the text", async (status, detail, copy) => {
    mocked.mockResolvedValue({ ok: false, status, ...(detail ? { detail } : {}) });
    render(<Harness />);
    const box = screen.getByRole("textbox", { name: "Note" });
    await userEvent.type(box, "keep me");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(copy);
    expect(box).toHaveValue("keep me");
    expect(localStorage.getItem(KEY)).toBe("keep me");
  });

  it("restores the draft after closing and reopening", async () => {
    const { rerender } = render(<CaptureDialog open onOpenChange={vi.fn()} />);
    await userEvent.type(screen.getByRole("textbox", { name: "Note" }), "draft");
    rerender(<CaptureDialog open={false} onOpenChange={vi.fn()} />);
    expect(screen.queryByRole("textbox", { name: "Note" })).not.toBeInTheDocument();
    rerender(<CaptureDialog open onOpenChange={vi.fn()} />);
    expect(screen.getByRole("textbox", { name: "Note" })).toHaveValue("draft");
  });

  it("does not accept typing while a save is in flight and keeps the text", async () => {
    let resolve: (r: Awaited<ReturnType<typeof captureNote>>) => void = () => {};
    mocked.mockReturnValue(new Promise((r) => (resolve = r)));
    render(<Harness />);
    const box = screen.getByRole("textbox", { name: "Note" });
    await userEvent.type(box, "one");
    await userEvent.keyboard("{Control>}{Enter}{/Control}");
    expect(box).toHaveAttribute("readonly");
    await userEvent.type(box, "more");
    expect(box).toHaveValue("one");
    await act(async () => {
      resolve({ ok: true, path: "p", title: "t", obsidian_url: null });
    });
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("keeps text that differs from what was sent", async () => {
    let resolve: (r: Awaited<ReturnType<typeof captureNote>>) => void = () => {};
    mocked.mockReturnValue(new Promise((r) => (resolve = r)));
    render(<Harness />);
    const box = screen.getByRole("textbox", { name: "Note" });
    await userEvent.type(box, "one");
    await userEvent.keyboard("{Control>}{Enter}{/Control}");
    fireEvent.change(box, { target: { value: "one two" } });
    await act(async () => {
      resolve({ ok: true, path: "p", title: "t", obsidian_url: null });
    });
    expect(box).toHaveValue("one two");
    expect(localStorage.getItem(KEY)).toBe("one two");
  });

  it("submits once for repeated Ctrl+Enter and a Save click", async () => {
    mocked.mockReturnValue(new Promise(() => {}));
    render(<Harness />);
    await userEvent.type(screen.getByRole("textbox", { name: "Note" }), "x");
    await userEvent.keyboard("{Control>}{Enter}{Enter}{/Control}");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(mocked).toHaveBeenCalledTimes(1);
  });

  it("shows the session-ended copy for a 401 and keeps the text", async () => {
    mocked.mockResolvedValue({ ok: false, status: 401 });
    render(<Harness />);
    await userEvent.type(screen.getByRole("textbox", { name: "Note" }), "keep");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your session ended. Sign in again.",
    );
    expect(screen.getByRole("textbox", { name: "Note" })).toHaveValue("keep");
  });

  it("clears the error on edit and on reopen", async () => {
    mocked.mockResolvedValue({ ok: false, status: 500 });
    const { rerender } = render(<CaptureDialog open onOpenChange={vi.fn()} />);
    await userEvent.type(screen.getByRole("textbox", { name: "Note" }), "a");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByRole("alert");
    await userEvent.type(screen.getByRole("textbox", { name: "Note" }), "b");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByRole("alert");
    rerender(<CaptureDialog open={false} onOpenChange={vi.fn()} />);
    rerender(<CaptureDialog open onOpenChange={vi.fn()} />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
