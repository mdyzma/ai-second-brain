import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import { chatKeys } from "./api";
import { isFinished, startTurn, streamTurn, type TurnState, turnReducer } from "./turn";

/**
 * One in-flight turn per conversation. A finished turn is replaced by the saved one after the
 * refetch; a failed or stopped turn stays visible (marked "not saved") until the next send.
 * Navigating away does not abort: the answer finishes and is saved server-side.
 */
export function useTurn(sessionId: string) {
  const queryClient = useQueryClient();
  const [turn, setTurn] = useState<TurnState | null>(null);
  const controller = useRef<AbortController | null>(null);

  const send = useCallback(
    async (question: string) => {
      if (controller.current !== null) return;
      const abort = new AbortController();
      controller.current = abort;
      setTurn(startTurn(question));
      await streamTurn(sessionId, question, abort.signal, (action) => {
        setTurn((state) => (state === null ? state : turnReducer(state, action)));
      });
      controller.current = null;
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: chatKeys.session(sessionId) }),
        queryClient.invalidateQueries({ queryKey: chatKeys.sessions }),
      ]);
      setTurn((state) => (state !== null && state.phase === "done" ? null : state));
    },
    [queryClient, sessionId],
  );

  const stop = useCallback(() => controller.current?.abort(), []);

  return { turn, busy: turn !== null && !isFinished(turn), send, stop };
}
