import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { chatKeys, chatStatusQueryOptions, createSession } from "@/features/chat/api";
import { NewSession } from "@/features/chat/components/NewSession";
import { setPendingQuestion } from "@/features/chat/pending";
import type { ChatMode } from "@/features/chat/types";

export const Route = createFileRoute("/_app/ask/")({ component: NewSessionRoute });

function NewSessionRoute() {
  const status = useQuery(chatStatusQueryOptions);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  async function start(mode: ChatMode, question: string): Promise<string | null> {
    const result = await createSession(mode);
    if (!result.ok) return result.message;
    setPendingQuestion(result.session.id, question);
    await queryClient.invalidateQueries({ queryKey: chatKeys.sessions });
    await navigate({ to: "/ask/$sessionId", params: { sessionId: result.session.id } });
    return null;
  }

  return <NewSession status={status.data} onStart={start} />;
}
