import { useState } from "react";
import type { ChatMode, ChatStatus } from "../types";
import { ChatComposer } from "./ChatComposer";
import { ModeSwitcher } from "./ModeSwitcher";
import { SystemBanner } from "./SystemBanner";

type Props = {
  status: ChatStatus | undefined;
  onStart: (mode: ChatMode, question: string) => Promise<string | null>;
};

export function disabledReasonFor(mode: ChatMode, status: ChatStatus | undefined): string | null {
  if (status === undefined) return null;
  if (mode === "private" && !status.private.available) return "No local model reachable.";
  if (mode === "cloud" && !status.cloud.available) return "Cloud mode is not configured.";
  return null;
}

export function NewSession({ status, onStart }: Props) {
  const [mode, setMode] = useState<ChatMode>("private");
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  async function start(question: string): Promise<void> {
    setStarting(true);
    setError(null);
    try {
      setError(await onStart(mode, question));
    } finally {
      setStarting(false);
    }
  }

  return (
    <section aria-label="New conversation" className="flex max-w-2xl flex-col gap-4">
      <SystemBanner status={status} mode={mode} />
      <ModeSwitcher
        value={mode}
        onChange={setMode}
        cloudAvailable={status?.cloud.available ?? false}
      />
      <ChatComposer
        label={mode === "private" ? "Ask privately" : "Ask cloud"}
        onSend={(question) => void start(question)}
        onStop={() => {}}
        streaming={starting}
        disabledReason={disabledReasonFor(mode, status)}
      />
      {error !== null ? (
        <p
          role="alert"
          className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg"
        >
          {error}
        </p>
      ) : null}
    </section>
  );
}
