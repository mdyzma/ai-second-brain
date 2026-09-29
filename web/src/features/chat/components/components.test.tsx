import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ChatStatus, Source } from "../types";
import { AnswerBlock, safeUrl } from "./AnswerBlock";
import { ChatComposer } from "./ChatComposer";
import { ModeSwitcher } from "./ModeSwitcher";
import { SourceList } from "./SourceList";
import { SystemBanner } from "./SystemBanner";
import { TierBadge } from "./TierBadge";

const SOURCE: Source = {
  n: 1,
  source_id: "a",
  path: "notes/nas.md",
  heading: "Backups",
  score: 0.8123,
  snippet: "Nightly at 02:00",
};
const DOWN: ChatStatus = {
  private: { available: false, endpoints: [] },
  cloud: { available: false, model: null },
};

describe("TierBadge", () => {
  it("states the tier in text", () => {
    render(<TierBadge tier={{ kind: "cloud" }} />);
    expect(screen.getByText("Cloud · Anthropic — messages leave your network")).toBeInTheDocument();
  });

  it("marks a degraded private model", () => {
    render(<TierBadge tier={{ kind: "private", endpoint: "cpu", model: "s", degraded: true }} />);
    expect(screen.getByText(/Private — small local model/)).toBeInTheDocument();
  });
});

describe("ModeSwitcher", () => {
  it("defaults to private and explains cloud", async () => {
    const onChange = vi.fn();
    render(<ModeSwitcher value="private" onChange={onChange} cloudAvailable />);
    expect(screen.getByRole("radio", { name: /Private/ })).toBeChecked();
    expect(
      screen.getByText("Local memory is off. What you type is sent to Anthropic."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /Cloud/ }));
    expect(onChange).toHaveBeenCalledWith("cloud");
  });

  it("disables cloud without a key and says why", () => {
    render(<ModeSwitcher value="private" onChange={vi.fn()} cloudAvailable={false} />);
    expect(screen.getByRole("radio", { name: /Cloud/ })).toBeDisabled();
    expect(screen.getByText("Cloud mode needs SB_ANTHROPIC_API_KEY.")).toBeInTheDocument();
  });
});

describe("SourceList", () => {
  it("renders cards with anchors", () => {
    render(<SourceList sources={[SOURCE]} disabled={false} anchorPrefix="turn-1" />);
    expect(screen.getByText("notes/nas.md")).toBeInTheDocument();
    expect(screen.getByText("0.81")).toBeInTheDocument();
    expect(document.getElementById("turn-1-source-1")).not.toBeNull();
  });

  it("says when nothing matched, when memory is off and while searching", () => {
    const { rerender } = render(<SourceList sources={[]} disabled={false} anchorPrefix="t" />);
    expect(
      screen.getByText("No matching local sources — this answer is not based on your notes."),
    ).toBeInTheDocument();
    rerender(<SourceList sources={[]} disabled anchorPrefix="t" />);
    expect(screen.getByText("Local memory is off in cloud sessions.")).toBeInTheDocument();
    rerender(<SourceList sources={null} disabled={false} anchorPrefix="t" />);
    expect(screen.getByText("Searching your notes…")).toBeInTheDocument();
  });
});

describe("AnswerBlock", () => {
  it("renders markdown and links citations to sources", () => {
    render(
      <AnswerBlock
        text={"**Nightly** at 02:00 [1] and [4]."}
        state="done"
        sourceCount={1}
        anchorPrefix="t1"
      />,
    );
    expect(screen.getByText("Nightly").tagName).toBe("STRONG");
    expect(screen.getByRole("link", { name: "[1]" })).toHaveAttribute("href", "#t1-source-1");
    expect(screen.queryByRole("link", { name: "[4]" })).toBeNull();
  });

  it("never renders raw HTML and drops unsafe links", () => {
    const { container } = render(
      <AnswerBlock
        text={
          '<img src=x onerror="alert(1)"><script>alert(2)</script> [click](javascript:alert(3)) [ok](https://example.com)'
        }
        state="done"
        sourceCount={0}
        anchorPrefix="t"
      />,
    );
    expect(container.querySelector("img, script")).toBeNull();
    expect(screen.queryByRole("link", { name: "click" })).toBeNull();
    const ok = screen.getByRole("link", { name: "ok" });
    expect(ok).toHaveAttribute("target", "_blank");
    expect(ok).toHaveAttribute("rel", "noreferrer noopener");
  });

  it("shows stream states in words", () => {
    const { rerender } = render(
      <AnswerBlock text="part" state="interrupted" sourceCount={0} anchorPrefix="t" />,
    );
    expect(screen.getByText("Stopped — not saved.")).toBeInTheDocument();
    rerender(
      <AnswerBlock
        text=""
        state="error"
        errorMessage="No local model is reachable."
        sourceCount={0}
        anchorPrefix="t"
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("No local model is reachable. Not saved.");
    rerender(
      <AnswerBlock
        text=""
        state="streaming"
        placeholder="Searching your notes…"
        sourceCount={0}
        anchorPrefix="t"
      />,
    );
    expect(screen.getByTestId("answer")).toHaveAttribute("aria-busy", "true");
  });

  it("links citations only in normal text", () => {
    render(
      <AnswerBlock
        text={"see [1] and [2](x) and [9]\n\nuse `arr[1]` here\n\n```\nx[1]\n```"}
        state="done"
        sourceCount={3}
        anchorPrefix="p"
      />,
    );
    const links = screen.getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(["[1]"]);
    expect(links[0]).toHaveAttribute("href", "#p-source-1");
    expect(screen.getByText("arr[1]").tagName).toBe("CODE");
    expect(screen.getByText("x[1]").tagName).toBe("CODE");
    expect(screen.getByText(/and \[9\]/)).toBeInTheDocument();
  });

  it("never renders images or their remote sources", () => {
    const { container } = render(
      <AnswerBlock
        text={"![secret](https://attacker.example/x.png?q=1) done"}
        state="done"
        sourceCount={0}
        anchorPrefix="t"
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.innerHTML).not.toContain("attacker.example");
    expect(container).toHaveTextContent("secret");
  });

  it("helpers", () => {
    expect(safeUrl("javascript:alert(1)")).toBe("");
    expect(safeUrl("#p-source-1")).toBe("#p-source-1");
    expect(safeUrl("https://a.example/x")).toBe("https://a.example/x");
    expect(safeUrl("/relative")).toBe("");
  });
});

describe("ChatComposer", () => {
  it("sends on Enter, adds a newline on Shift+Enter, and clears", async () => {
    const onSend = vi.fn();
    render(
      <ChatComposer
        label="Ask privately"
        onSend={onSend}
        onStop={vi.fn()}
        streaming={false}
        disabledReason={null}
      />,
    );
    const box = screen.getByLabelText("Ask privately");
    await userEvent.type(box, "line one{Shift>}{Enter}{/Shift}line two{Enter}");
    expect(onSend).toHaveBeenCalledWith("line one\nline two");
    expect(box).toHaveValue("");
  });

  it("ignores blank input and shows the counter near the limit", async () => {
    const onSend = vi.fn();
    render(
      <ChatComposer
        label="Ask"
        onSend={onSend}
        onStop={vi.fn()}
        streaming={false}
        disabledReason={null}
      />,
    );
    await userEvent.type(screen.getByLabelText("Ask"), "   {Enter}");
    expect(onSend).not.toHaveBeenCalled();
    await userEvent.click(screen.getByLabelText("Ask"));
    await userEvent.paste("x".repeat(7000));
    expect(screen.getByText("7003 / 8000")).toBeInTheDocument();
  });

  it("offers Stop while streaming", async () => {
    const onStop = vi.fn();
    render(
      <ChatComposer label="Ask" onSend={vi.fn()} onStop={onStop} streaming disabledReason={null} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Stop generating" }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("is disabled with a visible reason", () => {
    render(
      <ChatComposer
        label="Ask"
        onSend={vi.fn()}
        onStop={vi.fn()}
        streaming={false}
        disabledReason="No local model reachable."
      />,
    );
    expect(screen.getByLabelText("Ask")).toBeDisabled();
    expect(screen.getByText("No local model reachable.")).toBeInTheDocument();
  });
});

describe("SystemBanner", () => {
  it("appears only for private mode without a local model", () => {
    const { rerender, container } = render(<SystemBanner status={DOWN} mode="private" />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "No local model reachable. Private questions can't be answered right now. Nothing was sent to the cloud.",
    );
    rerender(<SystemBanner status={DOWN} mode="cloud" />);
    expect(container).toBeEmptyDOMElement();
    rerender(<SystemBanner status={undefined} mode="private" />);
    expect(container).toBeEmptyDOMElement();
  });
});
