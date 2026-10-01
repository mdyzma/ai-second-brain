import { render, screen } from "@testing-library/react";
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
});
