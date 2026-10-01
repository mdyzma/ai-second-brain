import { useEffect, useRef, useState } from "react";
import { isObsidianUrl } from "@/api/obsidian";
import { cn } from "@/design-system/cn";
import { Button } from "@/design-system/ui/button";
import { Card } from "@/design-system/ui/card";
import { Input } from "@/design-system/ui/input";
import { errorCopy, snippetParts, VECTOR_UNAVAILABLE } from "./labels";
import type { SearchFacets, SearchHit, SearchResponse } from "./types";
import type { SearchChange, SearchState } from "./url";

const DEBOUNCE_MS = 250;
const MIN_QUERY = 2;
const TOP_TAGS = 12;

type Props = {
  state: SearchState;
  onState: (next: SearchState, change: SearchChange) => void;
  /** Save a query to recent searches (Enter, a result click). */
  onRemember: (q: string) => void;
  response?: SearchResponse | undefined;
  facets?: SearchFacets | undefined;
  loading: boolean;
  error?: number | undefined;
  errorDetail?: string | undefined;
  recent: string[];
  onClearRecent: () => void;
};

const BADGE = "rounded-sm border border-border bg-surface px-1.5 py-0.5 text-xs text-fg-muted";
const CHIP =
  "rounded-md border px-2 py-1 text-xs transition-colors aria-pressed:border-accent aria-pressed:bg-accent aria-pressed:text-accent-fg border-border-input bg-surface-raised text-fg hover:bg-surface";

function Snippet({ snippet }: { snippet: string }) {
  let offset = 0;
  return (
    <p className="mt-1 text-sm text-fg-muted">
      {snippetParts(snippet).map((part) => {
        const key = offset;
        offset += part.text.length;
        return part.mark ? (
          <mark key={key} className="rounded-sm bg-warning-bg px-0.5 text-fg">
            {part.text}
          </mark>
        ) : (
          <span key={key}>{part.text}</span>
        );
      })}
    </p>
  );
}

function Result({ hit, onOpen }: { hit: SearchHit; onOpen: () => void }) {
  const trail = hit.heading_path.join(" › ");
  return (
    <li className="rounded-lg border border-border bg-surface-raised p-4">
      <div className="flex flex-wrap items-center gap-2">
        {isObsidianUrl(hit.obsidian_url) ? (
          <a
            href={hit.obsidian_url}
            onClick={onOpen}
            className="font-medium text-accent underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-ring"
          >
            {hit.title ?? hit.path}
          </a>
        ) : (
          <span className="font-medium">{hit.title ?? hit.path}</span>
        )}
        {hit.matched.includes("text") && <span className={BADGE}>Text</span>}
        {hit.matched.includes("vector") && <span className={BADGE}>Meaning</span>}
      </div>
      <p className="mt-0.5 font-mono text-xs text-fg-muted">{hit.path}</p>
      {hit.heading_path.length > 0 && <p className="mt-0.5 text-xs text-fg-muted">{trail}</p>}
      <Snippet snippet={hit.snippet} />
    </li>
  );
}

export function SearchScreen({
  state,
  onState,
  onRemember,
  response,
  facets,
  loading,
  error,
  errorDetail,
  recent,
  onClearRecent,
}: Props) {
  const [text, setText] = useState(state.q);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef({ state, onState });
  latest.current = { state, onState };
  const [tagFilter, setTagFilter] = useState("");

  // Follow the URL (back/forward, recent-search clicks) unless a local edit is pending.
  useEffect(() => {
    if (timer.current === null) setText(state.q);
  }, [state.q]);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      const el = e.target;
      if (
        el instanceof HTMLElement &&
        (el instanceof HTMLInputElement ||
          el instanceof HTMLTextAreaElement ||
          el instanceof HTMLSelectElement ||
          el.isContentEditable)
      )
        return;
      e.preventDefault();
      inputRef.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const commit = (q: string, change: SearchChange = "commit") => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    latest.current.onState({ ...latest.current.state, q }, change);
  };
  const onChange = (q: string) => {
    setText(q);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => commit(q, "typing"), DEBOUNCE_MS);
  };

  const links = () => Array.from(listRef.current?.querySelectorAll<HTMLElement>("a") ?? []);
  const moveFocus = (delta: 1 | -1, from: Element | null) => {
    const all = links();
    if (all.length === 0) return false;
    const at = from ? all.findIndex((a) => a === from || a.contains(from)) : -1;
    const next = at === -1 ? (delta === 1 ? 0 : all.length - 1) : at + delta;
    if (next < 0) {
      inputRef.current?.focus();
      return true;
    }
    all[Math.min(next, all.length - 1)]?.focus();
    return true;
  };

  const hasFilters = Boolean(state.folder) || state.tags.length > 0;
  const folders = facets?.folders ?? [];
  const allTags = facets?.tags ?? [];
  const top = allTags.slice(0, TOP_TAGS).map((t) => t.tag);
  const visible = [...top, ...state.tags.filter((t) => !top.includes(t))];
  const rest = allTags
    .map((t) => t.tag)
    .filter((t) => !visible.includes(t))
    .filter((t) => t.toLowerCase().includes(tagFilter.trim().toLowerCase()));
  const toggleTag = (tag: string) =>
    onState(
      {
        ...state,
        tags: state.tags.includes(tag) ? state.tags.filter((t) => t !== tag) : [...state.tags, tag],
      },
      "commit",
    );

  const queryReady = state.q.trim().length >= MIN_QUERY;
  const results = response?.results ?? [];
  const count = results.length;
  const status =
    queryReady && response && error === undefined && !loading
      ? `${count} ${count === 1 ? "result" : "results"}`
      : "";

  const chip = (tag: string) => (
    <button
      key={tag}
      type="button"
      aria-pressed={state.tags.includes(tag)}
      onClick={() => toggleTag(tag)}
      className={CHIP}
    >
      {tag}
    </button>
  );

  return (
    <div className="max-w-3xl space-y-4">
      <h1 className="text-2xl font-semibold">Search</h1>
      <Input
        ref={inputRef}
        type="search"
        autoFocus
        aria-label="Search your notes"
        placeholder="Search your notes (press / to focus)"
        value={text}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            commit(text);
            if (text.trim().length >= MIN_QUERY) onRemember(text.trim());
          } else if (e.key === "ArrowDown" && moveFocus(1, null)) e.preventDefault();
        }}
      />

      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Folder"
          value={state.folder ?? ""}
          onChange={(e) => {
            const { folder: _drop, ...rest } = state;
            onState(e.target.value ? { ...rest, folder: e.target.value } : rest, "commit");
          }}
          className="h-8 rounded-md border border-border-input bg-surface-raised px-2 text-sm text-fg"
        >
          <option value="">All folders</option>
          {state.folder && !folders.some((f) => f.path === state.folder) && (
            <option value={state.folder}>{state.folder}</option>
          )}
          {folders.map((f) => (
            <option key={f.path} value={f.path}>
              {f.path} ({f.count})
            </option>
          ))}
        </select>
        {visible.map(chip)}
        {rest.length > 0 || tagFilter ? (
          <details className="relative">
            <summary className="cursor-pointer rounded-md border border-border-input bg-surface-raised px-2 py-1 text-xs text-fg">
              More…
            </summary>
            <div className="mt-2 space-y-2 rounded-md border border-border bg-surface-raised p-2">
              <Input
                aria-label="Filter tags"
                placeholder="Filter tags"
                className="h-8"
                value={tagFilter}
                onChange={(e) => setTagFilter(e.target.value)}
              />
              <div className="flex max-w-md flex-wrap gap-2">{rest.map(chip)}</div>
            </div>
          </details>
        ) : null}
        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onState({ q: state.q, tags: [] }, "commit")}
          >
            Clear filters
          </Button>
        )}
      </div>

      <p role="status" className="sr-only">
        {status}
      </p>

      {error !== undefined && (
        <p role="alert" className="text-sm text-danger-fg">
          {errorCopy(error, errorDetail)}
        </p>
      )}

      {!queryReady && error === undefined && (
        <Card>
          <p className="text-sm text-fg-muted">
            Type at least {MIN_QUERY} characters to search your notes.
          </p>
          {recent.length > 0 && (
            <div className="mt-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-medium">Recent searches</h2>
                <Button variant="ghost" size="sm" onClick={onClearRecent}>
                  Clear
                </Button>
              </div>
              <ul className="mt-2 flex flex-wrap gap-2">
                {recent.map((q) => (
                  <li key={q}>
                    <button
                      type="button"
                      className={CHIP}
                      onClick={() => {
                        setText(q);
                        commit(q);
                      }}
                    >
                      {q}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      )}

      {queryReady && error === undefined && !response && loading && (
        <p className="text-sm text-fg-muted">Searching…</p>
      )}

      {queryReady && error === undefined && response?.vector === "unavailable" && (
        <p className="rounded-md border border-warning-border bg-warning-bg px-3 py-2 text-sm text-warning-fg">
          {VECTOR_UNAVAILABLE}
        </p>
      )}

      {queryReady && error === undefined && response && count === 0 && (
        <p className="text-sm text-fg-muted">
          No notes match.{hasFilters ? " Try clearing the filters." : ""}
        </p>
      )}

      {queryReady && error === undefined && count > 0 && (
        <ol
          ref={listRef}
          aria-label="Search results"
          aria-busy={loading}
          className={cn("space-y-3", loading && "opacity-60")}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
              if (moveFocus(e.key === "ArrowDown" ? 1 : -1, document.activeElement))
                e.preventDefault();
            }
          }}
        >
          {results.map((hit) => (
            <Result
              key={`${hit.source_id}:${hit.heading_path.join("/")}:${hit.snippet}`}
              hit={hit}
              onOpen={() => onRemember(state.q)}
            />
          ))}
        </ol>
      )}
    </div>
  );
}
