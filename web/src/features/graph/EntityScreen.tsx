import { Link } from "@tanstack/react-router";
import { isObsidianUrl } from "@/api/obsidian";
import { BADGE } from "./EntitiesScreen";
import { RELATION_LABEL, TYPE_LABEL } from "./labels";
import type { EntityDetail } from "./types";

type Props = { entity?: EntityDetail | undefined; error: number | null };

const LINK =
  "text-accent underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-ring";

function EntityLink({ e }: { e: { id: string; name: string } }) {
  return (
    <Link to="/entities/$entityId" params={{ entityId: e.id }} className={LINK}>
      {e.name}
    </Link>
  );
}

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function EntityScreen({ entity, error }: Props) {
  if (error === 404) {
    return (
      <div className="max-w-3xl space-y-2">
        <p className="text-sm">This entity no longer exists (it may have been merged).</p>
        <Link to="/entities" className={`text-sm ${LINK}`}>
          Back to entities
        </Link>
      </div>
    );
  }
  if (error !== null) {
    return (
      <p role="alert" className="text-sm text-danger-fg">
        Couldn't load this entity. Try again.
      </p>
    );
  }
  if (!entity) return <p className="text-sm text-fg-muted">Loading…</p>;

  const groups = new Map<string, { label: string; entities: { id: string; name: string }[] }>();
  for (const r of entity.related) {
    const [forward, reverse] = RELATION_LABEL[r.relation];
    const key = `${r.relation}:${r.direction}`;
    const group = groups.get(key) ?? {
      label: capitalize(r.direction === "out" ? forward : reverse),
      entities: [],
    };
    group.entities.push(r.entity);
    groups.set(key, group);
  }

  return (
    <div className="max-w-3xl space-y-6">
      <header className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold">{entity.name}</h1>
          <span className={BADGE}>{TYPE_LABEL[entity.type]}</span>
        </div>
        {entity.aliases.length > 0 && (
          <p className="text-sm text-fg-muted">Also known as {entity.aliases.join(", ")}</p>
        )}
        <Link to="/entities" className={`text-sm ${LINK}`}>
          All entities
        </Link>
      </header>

      {(entity.parent || entity.children.length > 0) && (
        <section aria-labelledby="hierarchy" className="space-y-1">
          <h2 id="hierarchy" className="text-lg font-medium">
            Hierarchy
          </h2>
          {entity.parent && (
            <p className="text-sm">
              Parent: <EntityLink e={entity.parent} />
            </p>
          )}
          {entity.children.length > 0 && (
            <>
              <p className="text-sm">Children:</p>
              <ul className="list-disc pl-5 text-sm">
                {entity.children.map((c) => (
                  <li key={c.id}>
                    <EntityLink e={c} />
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      {groups.size > 0 && (
        <section aria-labelledby="related" className="space-y-1">
          <h2 id="related" className="text-lg font-medium">
            Related
          </h2>
          <ul className="space-y-1 text-sm">
            {[...groups.entries()].map(([key, g]) => (
              <li key={key}>
                {g.label}:{" "}
                {g.entities.map((e, i) => (
                  <span key={e.id}>
                    {i > 0 && ", "}
                    <EntityLink e={e} />
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="notes" className="space-y-2">
        <h2 id="notes" className="text-lg font-medium">
          Notes
        </h2>
        {entity.notes.length === 0 ? (
          <p className="text-sm text-fg-muted">No notes mention this entity yet.</p>
        ) : (
          <ul className="space-y-2">
            {entity.notes.map((n) => (
              <li
                key={`${n.source_id}:${n.heading ?? ""}:${n.relation}`}
                className="rounded-lg border border-border bg-surface-raised p-4"
              >
                {isObsidianUrl(n.obsidian_url) ? (
                  <a href={n.obsidian_url} className={`font-medium ${LINK}`}>
                    {n.title ?? n.path}
                  </a>
                ) : (
                  <span className="font-medium">{n.title ?? n.path}</span>
                )}
                <p className="mt-0.5 font-mono text-xs text-fg-muted">{n.path}</p>
                {n.heading && <p className="mt-0.5 text-xs text-fg-muted">{n.heading}</p>}
                {n.summary && <p className="mt-1 text-sm text-fg-muted">{n.summary}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
