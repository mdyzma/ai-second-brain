import type { ReactNode } from "react";
import { isObsidianUrl } from "@/api/obsidian";
import type { Source } from "../types";

type Props = { sources: Source[] | null; disabled: boolean; anchorPrefix: string };

function Note({ children }: { children: string }) {
  return <p className="text-sm text-fg-muted">{children}</p>;
}

export function SourceList({ sources, disabled, anchorPrefix }: Props) {
  let body: ReactNode;
  if (disabled) body = <Note>Local memory is off in cloud sessions.</Note>;
  else if (sources === null) body = <Note>Searching your notes…</Note>;
  else if (sources.length === 0)
    body = <Note>No matching local sources — this answer is not based on your notes.</Note>;
  else
    body = (
      <ol className="flex flex-col gap-2">
        {sources.map((source) => (
          <li
            key={source.n}
            id={`${anchorPrefix}-source-${source.n}`}
            className="rounded-md border border-border bg-surface-raised p-3 text-sm"
          >
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="font-semibold">[{source.n}]</span>
              {isObsidianUrl(source.obsidian_url) ? (
                <a
                  href={source.obsidian_url}
                  className="font-mono break-all underline-offset-2 hover:underline"
                >
                  {source.path}
                </a>
              ) : (
                <span className="font-mono break-all">{source.path}</span>
              )}
              {source.heading ? <span className="text-fg-muted">› {source.heading}</span> : null}
              <span className="ml-auto text-xs text-fg-muted" title="Relevance score">
                {source.score.toFixed(2)}
              </span>
            </div>
            <p className="mt-1 line-clamp-3 text-fg-muted">{source.snippet}</p>
          </li>
        ))}
      </ol>
    );
  return (
    <section aria-label="Sources" className="flex flex-col gap-2">
      <h3 className="text-xs font-semibold tracking-wide text-fg-muted uppercase">Sources</h3>
      {body}
    </section>
  );
}
