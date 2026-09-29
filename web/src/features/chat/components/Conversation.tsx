import type { ReactNode } from "react";
import { tierForServed, tierForSession, tierForTurn } from "../tier";
import type { TurnState } from "../turn";
import type { ChatStatus, SessionDetail } from "../types";
import type { AnswerState } from "./AnswerBlock";
import { ChatComposer } from "./ChatComposer";
import { disabledReasonFor } from "./NewSession";
import { SystemBanner } from "./SystemBanner";
import { TierBadge } from "./TierBadge";
import { TurnView } from "./TurnView";

type Props = {
  session: SessionDetail;
  status: ChatStatus | undefined;
  turn: TurnState | null;
  busy: boolean;
  onSend: (question: string) => void;
  onStop: () => void;
  header?: ReactNode;
};

const PLACEHOLDERS: Partial<Record<TurnState["phase"], string>> = {
  retrieving: "Searching your notes…",
  connecting: "Connecting to the model…",
  generating: "Waiting for the first words…",
};

function answerState(turn: TurnState): AnswerState {
  if (turn.phase === "done") return "done";
  if (turn.phase === "error") return "error";
  if (turn.phase === "interrupted") return "interrupted";
  return "streaming";
}

export function Conversation({ session, status, turn, busy, onSend, onStop, header }: Props) {
  const cloud = session.mode === "cloud";
  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center gap-3">
        {header}
        <h2 className="min-w-0 flex-1 truncate text-lg font-semibold">
          {session.title ?? "New conversation"}
        </h2>
        <TierBadge tier={tierForSession(session.mode, status)} />
      </header>
      <SystemBanner status={status} mode={session.mode} />
      <ol aria-label="Conversation" className="flex flex-col gap-8">
        {session.turns.map((saved) => (
          <li key={saved.id}>
            <TurnView
              question={saved.question}
              sources={saved.sources}
              sourcesDisabled={cloud}
              answer={saved.answer}
              state="done"
              tier={tierForTurn(saved)}
              anchorPrefix={`turn-${saved.seq}`}
            />
          </li>
        ))}
        {turn !== null ? (
          <li>
            <TurnView
              question={turn.question}
              sources={turn.sources}
              sourcesDisabled={turn.sourcesDisabled}
              answer={turn.answer}
              state={answerState(turn)}
              errorMessage={turn.error?.message}
              placeholder={PLACEHOLDERS[turn.phase]}
              tier={turn.served ? tierForServed(turn.served) : undefined}
              anchorPrefix="turn-current"
            />
          </li>
        ) : null}
      </ol>
      <ChatComposer
        label={cloud ? "Ask cloud" : "Ask privately"}
        onSend={onSend}
        onStop={onStop}
        streaming={busy}
        disabledReason={busy ? null : disabledReasonFor(session.mode, status)}
      />
    </div>
  );
}
