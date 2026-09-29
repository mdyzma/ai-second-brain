import { TriangleAlert } from "lucide-react";
import type { ChatMode, ChatStatus } from "../types";

export function SystemBanner({ status, mode }: { status: ChatStatus | undefined; mode: ChatMode }) {
  if (mode !== "private" || status === undefined || status.private.available) return null;
  return (
    <div
      role="status"
      className="flex items-start gap-2 rounded-md border border-warning-border bg-warning-bg px-3 py-2 text-sm text-warning-fg"
    >
      <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
      <p>
        No local model reachable. Private questions can't be answered right now. Nothing was sent to
        the cloud.
      </p>
    </div>
  );
}
