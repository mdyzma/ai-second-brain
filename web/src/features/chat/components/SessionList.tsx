import { Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/design-system/cn";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/design-system/ui/alert-dialog";
import { Button } from "@/design-system/ui/button";
import type { ChatSession } from "../types";

type Props = {
  sessions: ChatSession[];
  activeId?: string | undefined;
  onDelete: (id: string) => Promise<void>;
  renderLink: (session: ChatSession, className: string) => ReactNode;
};

export function SessionList({ sessions, activeId, onDelete, renderLink }: Props) {
  return (
    <nav aria-label="Conversations" className="flex flex-col gap-2">
      <h2 className="text-sm font-semibold">Conversations</h2>
      {sessions.length === 0 ? (
        <p className="text-sm text-fg-muted">No conversations yet.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {sessions.map((session) => {
            const title = session.title ?? "New conversation";
            return (
              <li
                key={session.id}
                className={cn(
                  "flex items-center gap-1 rounded-md pr-1",
                  session.id === activeId ? "bg-surface" : "hover:bg-surface",
                )}
              >
                {renderLink(session, "min-w-0 flex-1 truncate px-2 py-1.5 text-sm")}
                <span className="shrink-0 text-xs text-fg-muted">
                  {session.mode === "cloud" ? "Cloud" : "Private"}
                </span>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Delete conversation: ${title}`}
                      className="size-8"
                    >
                      <Trash2 aria-hidden />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
                    <AlertDialogDescription>This cannot be undone.</AlertDialogDescription>
                    <div className="mt-6 flex justify-end gap-2">
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction onClick={() => void onDelete(session.id)}>
                        Delete
                      </AlertDialogAction>
                    </div>
                  </AlertDialogContent>
                </AlertDialog>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}
