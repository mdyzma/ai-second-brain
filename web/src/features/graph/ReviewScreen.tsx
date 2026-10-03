import { useEffect, useId, useRef, useState } from "react";
import { isObsidianUrl } from "@/api/obsidian";
import { cn } from "@/design-system/cn";
import { Button } from "@/design-system/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/design-system/ui/dialog";
import { Input } from "@/design-system/ui/input";
import type { Result, RunResult } from "./api";
import {
  ENTITY_TYPES,
  entityErrorCopy,
  extractErrorCopy,
  linksErrorCopy,
  loadErrorCopy,
  NO_MODEL,
  queuedCopy,
  RELATION_LABEL,
  TYPE_LABEL,
} from "./labels";
import type {
  EntityDecision,
  EntitySummary,
  EntityType,
  ExtractScope,
  GraphStatus,
  LinkDecision,
  ReviewEntity,
  ReviewLink,
} from "./types";

const MAX_BATCH = 100;

export type ReviewScreenProps = {
  status: GraphStatus;
  entities: ReviewEntity[];
  entitiesLoading: boolean;
  /** HTTP status of a failed entities load (0 = network), else null. */
  entitiesError: number | null;
  hasMoreEntities: boolean;
  onLoadMoreEntities: () => void;
  links: ReviewLink[];
  linksLoading: boolean;
  linksError: number | null;
  hasMoreLinks: boolean;
  onLoadMoreLinks: () => void;
  onDecide: (id: string, body: EntityDecision) => Promise<Result>;
  onDecideLinks: (items: LinkDecision[]) => Promise<Result>;
  onRun: (scope: ExtractScope) => Promise<RunResult>;
  onSearch: (type: EntityType | undefined, q: string) => Promise<EntitySummary[]>;
};

type Tab = "entities" | "links";
type CardError = { text: string; nameTaken: boolean };
type PickerState = { entity: ReviewEntity; mode: "merge" | "parent" };

const SELECT_CLASS =
  "h-8 rounded-md border border-border-input bg-surface-raised px-2 text-sm text-fg";
const TYPING =
  'input, textarea, select, [contenteditable=""], [contenteditable="true"], [role="dialog"]';

function sum(status: GraphStatus, key: "proposed" | "accepted" | "rejected"): number {
  return Object.values(status.entities).reduce((n, c) => n + c[key], 0);
}

export function ReviewScreen(props: ReviewScreenProps) {
  const { status } = props;
  const [tab, setTab] = useState<Tab>("entities");
  const baseId = useId();
  const proposed = sum(status, "proposed");

  const tabs: { id: Tab; label: string; count: string | null }[] = [
    { id: "entities", label: "Entities", count: String(proposed) },
    {
      id: "links",
      label: "Links",
      count: props.linksLoading ? null : `${props.links.length}${props.hasMoreLinks ? "+" : ""}`,
    },
  ];

  return (
    <div className="space-y-5">
      <Header {...props} />
      <div
        role="tablist"
        aria-label="Review"
        className="flex gap-1 border-b border-border"
        onKeyDown={(e) => {
          if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
          e.preventDefault();
          const next: Tab = tab === "entities" ? "links" : "entities";
          setTab(next);
          document.getElementById(`${baseId}-tab-${next}`)?.focus();
        }}
      >
        {tabs.map((t) => (
          <button
            key={t.id}
            id={`${baseId}-tab-${t.id}`}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            aria-controls={`${baseId}-panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => setTab(t.id)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm font-medium",
              tab === t.id
                ? "border-accent text-fg"
                : "border-transparent text-fg-muted hover:text-fg",
            )}
          >
            {t.label}
            {t.count !== null ? ` (${t.count})` : ""}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${baseId}-panel-${tab}`} aria-labelledby={`${baseId}-tab-${tab}`}>
        {tab === "entities" ? <EntitiesPanel {...props} /> : <LinksPanel {...props} />}
      </div>
    </div>
  );
}

function Header({ status, onRun }: ReviewScreenProps) {
  const [open, setOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const menuId = useId();
  const unavailable = !status.available;
  const stats: [string, string][] = [
    ["Notes extracted", `${status.revisions.extracted} of ${status.revisions.total}`],
    ["Waiting", String(status.revisions.pending)],
    ["Failed", String(status.revisions.failed)],
    ["To review", String(sum(status, "proposed"))],
    ["Accepted", String(sum(status, "accepted"))],
    ["Rejected", String(sum(status, "rejected"))],
  ];

  async function run(scope: ExtractScope) {
    setOpen(false);
    setRunning(true);
    setError(null);
    setMessage(null);
    const result = await onRun(scope);
    setRunning(false);
    if (result.ok) setMessage(queuedCopy(result.queued));
    else setError(extractErrorCopy(result.status, result.detail));
  }

  return (
    <header className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <dl className="flex flex-wrap gap-x-6 gap-y-2">
          {stats.map(([label, value]) => (
            <div key={label}>
              <dt className="text-xs text-fg-muted">{label}</dt>
              <dd className="text-base font-semibold">{value}</dd>
            </div>
          ))}
        </dl>
        <div className="relative">
          <Button
            variant="outline"
            aria-haspopup="menu"
            aria-expanded={open}
            aria-controls={open ? menuId : undefined}
            disabled={unavailable || running}
            onClick={() => setOpen((o) => !o)}
          >
            Run extraction
          </Button>
          {open ? (
            <div
              id={menuId}
              role="menu"
              aria-label="Run extraction"
              className="absolute right-0 z-10 mt-1 w-44 rounded-md border border-border bg-surface-raised p-1 shadow-lg"
              onKeyDown={(e) => {
                if (e.key === "Escape") setOpen(false);
              }}
            >
              <button
                type="button"
                role="menuitem"
                className="block w-full rounded px-3 py-2 text-left text-sm hover:bg-surface"
                onClick={() => void run("new")}
              >
                New notes
              </button>
              <button
                type="button"
                role="menuitem"
                className="block w-full rounded px-3 py-2 text-left text-sm hover:bg-surface"
                onClick={() => void run("failed")}
              >
                Retry failed
              </button>
            </div>
          ) : null}
        </div>
      </div>
      {unavailable ? <p className="text-sm text-fg-muted">{NO_MODEL}</p> : null}
      <p role="status" className="text-sm text-fg-muted">
        {message}
      </p>
      {error ? (
        <p role="alert" className="text-sm text-danger-fg">
          {error}
        </p>
      ) : null}
    </header>
  );
}

function Feedback({
  loading,
  error,
  empty,
}: {
  loading: boolean;
  error: number | null;
  empty: boolean;
}) {
  if (error !== null)
    return (
      <p role="alert" className="text-sm text-danger-fg">
        {loadErrorCopy(error)}
      </p>
    );
  if (loading) return <p className="text-sm text-fg-muted">Loading…</p>;
  if (empty) return <p className="text-sm text-fg-muted">Nothing to review.</p>;
  return null;
}

function EntitiesPanel(props: ReviewScreenProps) {
  const { entities, onDecide, onSearch } = props;
  const listRef = useRef<HTMLDivElement>(null);
  const busy = useRef(new Set<string>());
  const [errors, setErrors] = useState<Record<string, CardError | null>>({});
  const [picker, setPicker] = useState<PickerState | null>(null);

  const cards = () =>
    Array.from(listRef.current?.querySelectorAll<HTMLElement>("article[data-entity-id]") ?? []);
  const focusId = (id: string | undefined) => {
    if (id)
      cards()
        .find((c) => c.dataset.entityId === id)
        ?.focus();
  };

  async function act(entity: ReviewEntity, body: EntityDecision, quiet = false): Promise<Result> {
    if (busy.current.has(entity.id)) return { ok: false, status: -1 };
    busy.current.add(entity.id);
    setErrors((e) => ({ ...e, [entity.id]: null }));
    const index = entities.findIndex((x) => x.id === entity.id);
    const neighbour = (entities[index + 1] ?? entities[index - 1])?.id;
    const result = await onDecide(entity.id, body);
    busy.current.delete(entity.id);
    if (result.ok) {
      if (["accept", "reject", "merge"].includes(body.action)) focusId(neighbour);
    } else if (!quiet) {
      setErrors((e) => ({
        ...e,
        [entity.id]: {
          text: entityErrorCopy(result.status, result.detail, entity.type),
          nameTaken: result.detail === "name_taken",
        },
      }));
    }
    return result;
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey || picker) return;
    const target = e.target instanceof HTMLElement ? e.target : null;
    if (!target || target.closest(TYPING)) return;
    const key = e.key.toLowerCase();
    if (!["a", "r", "m", "j", "k"].includes(key)) return;
    const list = cards();
    const current = target.closest<HTMLElement>("article[data-entity-id]");
    const index = current ? list.indexOf(current) : -1;
    if (key === "j" || key === "k") {
      const next = list[key === "j" ? index + 1 : index - 1];
      if (next) {
        e.preventDefault();
        next.focus();
      }
      return;
    }
    const entity = entities.find((x) => x.id === current?.dataset.entityId);
    if (!entity) return;
    e.preventDefault();
    if (key === "a") void act(entity, { action: "accept" });
    else if (key === "r") void act(entity, { action: "reject" });
    else setPicker({ entity, mode: "merge" });
  }

  return (
    <div className="space-y-4">
      <Feedback
        loading={props.entitiesLoading}
        error={props.entitiesError}
        empty={!props.entitiesLoading && props.entitiesError === null && entities.length === 0}
      />
      {/* biome-ignore lint/a11y/noStaticElementInteractions: shortcuts are handled for the whole list */}
      <div ref={listRef} onKeyDown={onKeyDown} className="space-y-4">
        {entities.map((entity, i) => (
          <EntityCard
            key={entity.id}
            entity={entity}
            first={i === 0}
            error={errors[entity.id] ?? null}
            act={act}
            openPicker={(mode) => setPicker({ entity, mode })}
          />
        ))}
      </div>
      {props.hasMoreEntities ? (
        <Button variant="outline" onClick={props.onLoadMoreEntities}>
          Load more
        </Button>
      ) : null}
      <Dialog open={picker !== null} onOpenChange={(o) => !o && setPicker(null)}>
        {picker ? (
          <PickerContent
            picker={picker}
            onSearch={onSearch}
            onPick={async (target) => {
              const body: EntityDecision =
                picker.mode === "merge"
                  ? { action: "merge", into_id: target.id }
                  : { action: "parent", parent_id: target.id };
              const result = await act(picker.entity, body, true);
              if (result.ok) setPicker(null);
              return result.ok
                ? null
                : entityErrorCopy(result.status, result.detail, picker.entity.type);
            }}
          />
        ) : null}
      </Dialog>
    </div>
  );
}

function EntityCard({
  entity,
  first,
  error,
  act,
  openPicker,
}: {
  entity: ReviewEntity;
  first: boolean;
  error: CardError | null;
  act: (entity: ReviewEntity, body: EntityDecision) => Promise<Result>;
  openPicker: (mode: "merge" | "parent") => void;
}) {
  const s = entity.suggestion;
  return (
    <article
      aria-label={entity.name}
      data-entity-id={entity.id}
      tabIndex={first ? 0 : -1}
      className="space-y-3 rounded-lg border border-border bg-surface-raised p-4 focus:outline-2 focus:outline-ring"
    >
      <div className="flex flex-wrap items-center gap-3">
        <Input
          key={`${entity.id}:${entity.name}`}
          aria-label="Name"
          defaultValue={entity.name}
          className="h-8 max-w-xs font-medium"
          onKeyDown={(e) => {
            if (e.key !== "Enter") return;
            const name = e.currentTarget.value.trim();
            if (name && name !== entity.name) void act(entity, { action: "rename", name });
          }}
        />
        <select
          aria-label="Type"
          className={SELECT_CLASS}
          value={entity.type}
          onChange={(e) => void act(entity, { action: "retype", type: e.target.value })}
        >
          {ENTITY_TYPES.map((t) => (
            <option key={t} value={t}>
              {TYPE_LABEL[t]}
            </option>
          ))}
        </select>
        <span className="text-sm text-fg-muted">
          {entity.mention_count} {entity.mention_count === 1 ? "mention" : "mentions"}
        </span>
      </div>
      {entity.aliases.length ? (
        <p className="text-xs text-fg-muted">Also: {entity.aliases.join(", ")}</p>
      ) : null}
      {entity.samples.length ? (
        <ul className="space-y-2">
          {entity.samples.map((sample) => (
            <li key={sample.path} className="text-sm">
              <span className="font-medium">{sample.title ?? sample.path}</span>
              {isObsidianUrl(sample.obsidian_url) ? (
                <>
                  {" "}
                  <a
                    href={sample.obsidian_url}
                    aria-label={`Open ${sample.title ?? sample.path} in Obsidian`}
                    className="text-accent underline"
                  >
                    Open in Obsidian
                  </a>
                </>
              ) : null}
              {sample.summary ? <p className="text-fg-muted">{sample.summary}</p> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {s ? (
        <p className="flex flex-wrap items-center gap-2 rounded-md border border-warning-border bg-warning-bg px-3 py-2 text-sm text-warning-fg">
          <span>
            Looks like {s.name} ({Math.round(s.similarity * 100)}% match)
          </span>
          <Button
            size="sm"
            variant="outline"
            aria-label={`Merge into ${s.name}`}
            onClick={() => void act(entity, { action: "merge", into_id: s.id })}
          >
            Merge
          </Button>
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="flex flex-wrap items-center gap-2 text-sm text-danger-fg">
          <span>{error.text}</span>
          {error.nameTaken ? (
            <Button size="sm" variant="outline" onClick={() => openPicker("merge")}>
              Merge
            </Button>
          ) : null}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          aria-keyshortcuts="a"
          onClick={() => void act(entity, { action: "accept" })}
        >
          Accept
        </Button>
        <Button
          size="sm"
          variant="outline"
          aria-keyshortcuts="r"
          onClick={() => void act(entity, { action: "reject" })}
        >
          Reject
        </Button>
        <Button
          size="sm"
          variant="outline"
          aria-keyshortcuts="m"
          onClick={() => openPicker("merge")}
        >
          Merge into…
        </Button>
        <Button size="sm" variant="outline" onClick={() => openPicker("parent")}>
          Set parent…
        </Button>
      </div>
    </article>
  );
}

function PickerContent({
  picker,
  onSearch,
  onPick,
}: {
  picker: PickerState;
  onSearch: ReviewScreenProps["onSearch"];
  onPick: (target: EntitySummary) => Promise<string | null>;
}) {
  const { entity, mode } = picker;
  const [q, setQ] = useState("");
  const [results, setResults] = useState<EntitySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(
      () => {
        void onSearch(mode === "merge" ? entity.type : undefined, q).then((items) => {
          if (!cancelled) setResults(items.filter((i) => i.id !== entity.id));
        });
      },
      q ? 250 : 0,
    );
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [q, mode, entity.id, entity.type, onSearch]);

  const title = mode === "merge" ? `Merge ${entity.name} into…` : `Set parent of ${entity.name}…`;
  return (
    <DialogContent>
      <DialogTitle>{title}</DialogTitle>
      <DialogDescription>
        {mode === "merge"
          ? `Pick an accepted ${entity.type} to merge this into.`
          : "Pick an accepted entity to be its parent."}
      </DialogDescription>
      <Input
        aria-label="Search entities"
        placeholder="Search…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        className="mt-4"
      />
      {error ? (
        <p role="alert" className="mt-2 text-sm text-danger-fg">
          {error}
        </p>
      ) : null}
      <ul className="mt-3 max-h-64 space-y-1 overflow-y-auto">
        {results === null ? <li className="text-sm text-fg-muted">Loading…</li> : null}
        {results?.length === 0 ? (
          <li className="text-sm text-fg-muted">No matching entities.</li>
        ) : null}
        {results?.map((r) => (
          <li key={r.id}>
            <button
              type="button"
              className="flex w-full items-center justify-between rounded px-3 py-2 text-left text-sm hover:bg-surface"
              onClick={async () => setError(await onPick(r))}
            >
              <span>{r.name}</span>
              <span className="text-xs text-fg-muted">
                {TYPE_LABEL[r.type]} · {r.note_count} {r.note_count === 1 ? "note" : "notes"}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </DialogContent>
  );
}

function LinksPanel({
  links,
  linksLoading,
  linksError,
  hasMoreLinks,
  onLoadMoreLinks,
  onDecideLinks,
}: ReviewScreenProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const ids = links.filter((l) => selected.has(l.id)).map((l) => l.id);

  async function decide(items: LinkDecision[]) {
    setPending(true);
    setError(null);
    const result = await onDecideLinks(items);
    setPending(false);
    if (result.ok) {
      setSelected((prev) => {
        const next = new Set(prev);
        for (const i of items) next.delete(i.id);
        return next;
      });
    } else setError(linksErrorCopy(result.status));
  }
  const batch = (decision: LinkDecision["decision"]) => decide(ids.map((id) => ({ id, decision })));
  const batchBlocked = pending || ids.length === 0 || ids.length > MAX_BATCH;

  return (
    <div className="space-y-4">
      <Feedback
        loading={linksLoading}
        error={linksError}
        empty={!linksLoading && linksError === null && links.length === 0}
      />
      {links.length ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={batchBlocked} onClick={() => void batch("accept")}>
            Accept selected
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={batchBlocked}
            onClick={() => void batch("reject")}
          >
            Reject selected
          </Button>
          <span className="text-sm text-fg-muted">
            {ids.length > MAX_BATCH
              ? `Select at most ${MAX_BATCH} at a time.`
              : `${ids.length} selected`}
          </span>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-danger-fg">
          {error}
        </p>
      ) : null}
      <ul className="space-y-2">
        {links.map((link) => {
          const subject = link.subject?.name ?? link.note?.title ?? link.note?.path ?? "";
          const forward = RELATION_LABEL[link.relation][0];
          const summary = `${subject} ${forward} ${link.object.name}`;
          return (
            <li
              key={link.id}
              className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-surface-raised px-3 py-2"
            >
              <input
                type="checkbox"
                aria-label={`Select ${summary}`}
                checked={selected.has(link.id)}
                onChange={(e) =>
                  setSelected((prev) => {
                    const next = new Set(prev);
                    if (e.target.checked) next.add(link.id);
                    else next.delete(link.id);
                    return next;
                  })
                }
              />
              <p className="min-w-0 flex-1 text-sm">
                <strong>{subject}</strong> {forward} <strong>{link.object.name}</strong>
                {link.evidence ? (
                  <span className="text-fg-muted">
                    {" · "}
                    {isObsidianUrl(link.evidence.obsidian_url) ? (
                      <a href={link.evidence.obsidian_url} className="text-accent underline">
                        {link.evidence.path}
                      </a>
                    ) : (
                      link.evidence.path
                    )}
                    {link.evidence.heading ? ` › ${link.evidence.heading}` : ""}
                  </span>
                ) : null}
              </p>
              <Button
                size="sm"
                disabled={pending}
                aria-label={`Accept: ${summary}`}
                onClick={() => void decide([{ id: link.id, decision: "accept" }])}
              >
                Accept
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={pending}
                aria-label={`Reject: ${summary}`}
                onClick={() => void decide([{ id: link.id, decision: "reject" }])}
              >
                Reject
              </Button>
            </li>
          );
        })}
      </ul>
      {hasMoreLinks ? (
        <Button variant="outline" onClick={onLoadMoreLinks}>
          Load more
        </Button>
      ) : null}
    </div>
  );
}
