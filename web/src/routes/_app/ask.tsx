import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link, Outlet, useNavigate, useParams } from "@tanstack/react-router";
import { cn } from "@/design-system/cn";
import { chatKeys, deleteSession, sessionsQueryOptions } from "@/features/chat/api";
import { SessionList } from "@/features/chat/components/SessionList";

export const Route = createFileRoute("/_app/ask")({ component: AskLayout });

function AskLayout() {
  const sessions = useQuery(sessionsQueryOptions);
  const { sessionId } = useParams({ strict: false });
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  async function handleDelete(id: string): Promise<void> {
    if (!(await deleteSession(id))) return;
    queryClient.removeQueries({ queryKey: chatKeys.session(id) });
    await queryClient.invalidateQueries({ queryKey: chatKeys.sessions });
    if (sessionId === id) await navigate({ to: "/ask" });
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className={cn("text-2xl font-semibold", sessionId && "sr-only md:not-sr-only")}>Ask</h1>
      <div className="flex flex-col gap-6 md:flex-row">
        <aside
          className={cn(
            "md:w-72 md:shrink-0",
            sessionId ? "hidden md:block" : "order-last md:order-first",
          )}
        >
          <SessionList
            sessions={sessions.data ?? []}
            activeId={sessionId}
            onDelete={handleDelete}
            renderLink={(session, className) => (
              <Link to="/ask/$sessionId" params={{ sessionId: session.id }} className={className}>
                {session.title ?? "New conversation"}
              </Link>
            )}
          />
        </aside>
        <div className="min-w-0 flex-1">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
