import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/design-system/cn";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import type { EntitiesState } from "./entityUrl";
import { ENTITY_TYPES, loadErrorCopy, TYPE_LABEL } from "./labels";
import type { EntitySummary } from "./types";

const DEBOUNCE_MS = 250;
export const BADGE =
  "rounded-sm border border-border bg-surface px-1.5 py-0.5 text-xs text-fg-muted";

export type EntitiesChange = "typing" | "commit";

export type EntitiesScreenProps = {
  state: EntitiesState;
  onState: (next: EntitiesState, change: EntitiesChange) => void;
  items: EntitySummary[];
  loading: boolean;
  error: number | null;
  hasMore: boolean;
  onLoadMore: () => void;
};

export function EntitiesScreen({
  state,
  onState,
  items,
  loading,
  error,
  hasMore,
  onLoadMore,
}: EntitiesScreenProps) {
  const [text, setText] = useState(state.q);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef({ state, onState });
  latest.current = { state, onState };

  // Follow the URL (back/forward) unless a local edit is pending.
  useEffect(() => {
    if (timer.current === null) setText(state.q);
  }, [state.q]);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const onChange = (q: string) => {
    setText(q);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      timer.current = null;
      latest.current.onState({ ...latest.current.state, q }, "typing");
    }, DEBOUNCE_MS);
  };
  const pick = (type: EntitiesState["type"]) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    onState(type ? { type, q: text } : { q: text }, "commit");
  };

  const tab = (type: EntitiesState["type"], label: string) => {
    const selected = state.type === type;
    return (
      <button
        key={label}
        type="button"
        role="tab"
        aria-selected={selected}
        onClick={() => pick(type)}
        className={cn(
          "rounded-md border px-2 py-1 text-xs transition-colors focus-visible:outline-2 focus-visible:outline-ring",
          selected
            ? "border-accent bg-accent text-accent-fg"
            : "border-border-input bg-surface-raised text-fg hover:bg-surface",
        )}
      >
        {label}
      </button>
    );
  };

  const filtered = Boolean(state.type) || state.q.trim() !== "";
  return (
    <div className="max-w-3xl space-y-4">
      <h1 className="text-2xl font-semibold">Entities</h1>
      <div role="tablist" aria-label="Entity type" className="flex flex-wrap gap-2">
        {tab(undefined, "All")}
        {ENTITY_TYPES.map((t) => tab(t, TYPE_LABEL[t]))}
      </div>
      <Input
        type="search"
        aria-label="Search entities"
        placeholder="Search entities by name"
        value={text}
        onChange={(e) => onChange(e.target.value)}
      />
      {error !== null ? (
        <p role="alert" className="text-sm text-danger-fg">
          {loadErrorCopy(error).replace("review queue", "entities")}
        </p>
      ) : loading ? (
        <p className="text-sm text-fg-muted">Loading…</p>
      ) : items.length === 0 ? (
        filtered ? (
          <p className="text-sm text-fg-muted">No entities match.</p>
        ) : (
          <p className="text-sm text-fg-muted">
            No entities yet. Run extraction from{" "}
            <Link to="/review" className="text-accent underline-offset-2 hover:underline">
              Review
            </Link>
            .
          </p>
        )
      ) : (
        <ul className="space-y-2">
          {items.map((e) => (
            <li key={e.id}>
              <Link
                to="/entities/$entityId"
                params={{ entityId: e.id }}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface-raised p-3 hover:bg-surface focus-visible:outline-2 focus-visible:outline-ring"
              >
                <span className="font-medium">{e.name}</span>
                <span className={BADGE}>{TYPE_LABEL[e.type]}</span>
                <span className="ml-auto text-xs text-fg-muted">
                  {e.note_count} {e.note_count === 1 ? "note" : "notes"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {hasMore && (
        <Button type="button" onClick={onLoadMore}>
          Load more
        </Button>
      )}
    </div>
  );
}
