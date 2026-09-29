import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { useEffect, useRef } from "react";
import { chatSessionQueryOptions, chatStatusQueryOptions } from "@/features/chat/api";
import { Conversation } from "@/features/chat/components/Conversation";
import { takePendingQuestion } from "@/features/chat/pending";
import { useTurn } from "@/features/chat/useTurn";

export const Route = createFileRoute("/_app/ask/$sessionId")({ component: SessionRoute });

function SessionRoute() {
  const { sessionId } = Route.useParams();
  // A new key per conversation resets the in-flight turn and the pending-question guard.
  return <SessionScreen key={sessionId} sessionId={sessionId} />;
}

function SessionScreen({ sessionId }: { sessionId: string }) {
  const detail = useQuery(chatSessionQueryOptions(sessionId));
  const status = useQuery(chatStatusQueryOptions);
  const { turn, busy, send, stop } = useTurn(sessionId);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const question = takePendingQuestion(sessionId);
    if (question !== undefined) void send(question);
  }, [sessionId, send]);

  const back = (
    <Link to="/ask" className="inline-flex items-center gap-1 text-sm text-fg-muted md:hidden">
      <ArrowLeft aria-hidden className="size-4" /> All conversations
    </Link>
  );

  if (detail.isPending) return <p className="text-sm text-fg-muted">Loading…</p>;
  if (detail.isError)
    return (
      <p role="alert" className="text-sm text-danger-fg">
        Couldn't load this conversation.
      </p>
    );
  if (detail.data === null)
    return (
      <div className="flex flex-col gap-2">
        {back}
        <p>This conversation no longer exists.</p>
        <Link to="/ask" className="text-accent underline">
          Start a new one
        </Link>
      </div>
    );

  return (
    <Conversation
      session={detail.data}
      status={status.data}
      turn={turn}
      busy={busy}
      onSend={(question) => void send(question)}
      onStop={stop}
      header={
        <>
          {back}
          <Link to="/ask" className="hidden text-sm text-accent md:inline">
            New conversation
          </Link>
        </>
      }
    />
  );
}
