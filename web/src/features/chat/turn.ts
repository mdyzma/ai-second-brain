import { notifyUnauthorized } from "@/api/client";
import { readSse, type SseMessage } from "./sse";
import type { ReceiptEvent, Source, TurnEvent } from "./types";

export type TurnPhase =
  | "retrieving"
  | "connecting"
  | "generating"
  | "done"
  | "error"
  | "interrupted";

export type TurnState = {
  question: string;
  phase: TurnPhase;
  sources: Source[] | null;
  sourcesDisabled: boolean;
  answer: string;
  served: { endpoint: string; model: string; degraded: boolean } | null;
  receipt: ReceiptEvent | null;
  error: { code: string; message: string } | null;
};

export type TurnAction =
  | { type: "event"; event: TurnEvent }
  | { type: "interrupted" }
  | { type: "failed"; code: RequestErrorCode; message: string };

export const REQUEST_ERRORS = {
  turn_in_progress: "Another answer is still being generated in this session.",
  not_found: "This conversation no longer exists.",
  invalid: "The question is empty or too long (8000 characters at most).",
  unreachable: "Can't reach the server.",
  incomplete: "The connection closed before the answer finished.",
} as const;
export type RequestErrorCode = keyof typeof REQUEST_ERRORS;

const FINISHED: ReadonlySet<TurnPhase> = new Set(["done", "error", "interrupted"]);
const EVENT_NAMES: ReadonlySet<string> = new Set([
  "status",
  "sources",
  "token",
  "receipt",
  "done",
  "error",
]);

export function startTurn(question: string): TurnState {
  return {
    question,
    phase: "retrieving",
    sources: null,
    sourcesDisabled: false,
    answer: "",
    served: null,
    receipt: null,
    error: null,
  };
}

export function isFinished(state: TurnState): boolean {
  return FINISHED.has(state.phase);
}

function applyEvent(state: TurnState, event: TurnEvent): TurnState {
  switch (event.event) {
    case "status":
      if (event.phase === "generating") {
        return {
          ...state,
          phase: "generating",
          served: {
            endpoint: event.endpoint ?? "",
            model: event.model ?? "",
            degraded: event.degraded ?? false,
          },
        };
      }
      return { ...state, phase: event.phase };
    case "sources":
      return { ...state, sources: event.items, sourcesDisabled: event.disabled };
    case "token":
      return { ...state, answer: state.answer + event.text };
    case "receipt":
      return { ...state, receipt: event };
    case "done":
      return { ...state, phase: "done" };
    case "error":
      return { ...state, phase: "error", error: { code: event.code, message: event.message } };
  }
}

export function turnReducer(state: TurnState, action: TurnAction): TurnState {
  if (isFinished(state)) return state;
  switch (action.type) {
    case "interrupted":
      return { ...state, phase: "interrupted" };
    case "failed":
      return { ...state, phase: "error", error: { code: action.code, message: action.message } };
    case "event":
      return applyEvent(state, action.event);
  }
}

export function toTurnEvent(message: SseMessage): TurnEvent | null {
  if (!EVENT_NAMES.has(message.event)) return null;
  try {
    const data = JSON.parse(message.data) as TurnEvent;
    return data.event === message.event ? data : null;
  } catch {
    return null;
  }
}

function failure(code: RequestErrorCode): TurnAction {
  return { type: "failed", code, message: REQUEST_ERRORS[code] };
}

function statusFailure(status: number): RequestErrorCode {
  if (status === 409) return "turn_in_progress";
  if (status === 404) return "not_found";
  if (status === 422) return "invalid";
  return "unreachable";
}

export async function streamTurn(
  sessionId: string,
  question: string,
  signal: AbortSignal,
  dispatch: (action: TurnAction) => void,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/turns`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ question }),
      credentials: "same-origin",
      signal,
    });
  } catch {
    dispatch(signal.aborted ? { type: "interrupted" } : failure("unreachable"));
    return;
  }
  if (!response.ok || response.body === null) {
    if (response.status === 401) notifyUnauthorized();
    dispatch(failure(statusFailure(response.status)));
    return;
  }
  let finished = false;
  try {
    for await (const message of readSse(response.body)) {
      const event = toTurnEvent(message);
      if (event === null) continue;
      dispatch({ type: "event", event });
      if (event.event === "done" || event.event === "error") finished = true;
    }
  } catch {
    // Reading failed: an abort (Stop) or a dropped connection; decided below.
  }
  if (!finished) dispatch(signal.aborted ? { type: "interrupted" } : failure("incomplete"));
}
