import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { Button } from "@/design-system/ui/button";

const LIMIT = 8000;
const COUNTER_FROM = 7000;

type Props = {
  label: string;
  onSend: (question: string) => void;
  onStop: () => void;
  streaming: boolean;
  disabledReason: string | null;
};

function length(text: string): number {
  return [...text].length; // code points, matching the server's limit
}

export function ChatComposer({ label, onSend, onStop, streaming, disabledReason }: Props) {
  const id = useId();
  const reasonId = useId();
  const [value, setValue] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);
  const wasStreaming = useRef(streaming);
  const count = length(value);
  const disabled = disabledReason !== null;

  useEffect(() => {
    if (wasStreaming.current && !streaming) box.current?.focus();
    wasStreaming.current = streaming;
  }, [streaming]);

  function submit(): void {
    const question = value.trim();
    if (disabled || streaming || question === "" || length(question) > LIMIT) return;
    onSend(question);
    setValue("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <textarea
        id={id}
        ref={box}
        rows={3}
        value={value}
        disabled={disabled}
        aria-describedby={disabled ? reasonId : undefined}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={onKeyDown}
        className="w-full resize-y rounded-md border border-border-input bg-surface-raised px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-60"
      />
      <div className="flex items-center gap-3">
        {disabled ? (
          <p id={reasonId} className="text-sm text-fg-muted">
            {disabledReason}
          </p>
        ) : (
          <p className="text-xs text-fg-muted">Enter to send · Shift+Enter for a new line</p>
        )}
        {count >= COUNTER_FROM ? (
          <span className={count > LIMIT ? "text-xs text-danger-fg" : "text-xs text-fg-muted"}>
            {`${count} / ${LIMIT}`}
          </span>
        ) : null}
        <div className="ml-auto">
          {streaming ? (
            <Button variant="outline" aria-label="Stop generating" onClick={onStop}>
              Stop
            </Button>
          ) : (
            <Button type="submit" disabled={disabled || value.trim() === "" || count > LIMIT}>
              Send
            </Button>
          )}
        </div>
      </div>
    </form>
  );
}
