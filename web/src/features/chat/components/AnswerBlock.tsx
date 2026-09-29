import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

export type AnswerState = "streaming" | "done" | "interrupted" | "error";

type Props = {
  text: string;
  state: AnswerState;
  errorMessage?: string | undefined;
  sourceCount: number;
  anchorPrefix: string;
  placeholder?: string | undefined;
};

const CITATION = /\[(\d{1,3})\](?!\()/g;

/** Turn "[n]" into an in-page link to source n (only for sources that exist). */
export function linkCitations(text: string, count: number, anchorPrefix: string): string {
  return text.replace(CITATION, (match, digits: string) => {
    const n = Number(digits);
    return n >= 1 && n <= count ? `[\\[${n}\\]](#${anchorPrefix}-source-${n})` : match;
  });
}

/** Only in-page anchors and absolute http(s) links survive. */
export function safeUrl(url: string): string {
  if (url.startsWith("#")) return url;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? url : "";
  } catch {
    return "";
  }
}

const components: Components = {
  a: ({ href, children }) => {
    if (!href) return <span>{children}</span>;
    const className = "text-accent underline underline-offset-2";
    if (href.startsWith("#"))
      return (
        <a href={href} className={className}>
          {children}
        </a>
      );
    return (
      <a href={href} target="_blank" rel="noreferrer noopener" className={className}>
        {children}
      </a>
    );
  },
};

export function AnswerBlock({
  text,
  state,
  errorMessage,
  sourceCount,
  anchorPrefix,
  placeholder,
}: Props) {
  return (
    <div
      data-testid="answer"
      aria-live="polite"
      aria-busy={state === "streaming"}
      className="flex flex-col gap-2 text-sm leading-relaxed [&_ol]:list-decimal [&_ol]:pl-5 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-surface [&_pre]:p-3 [&_ul]:list-disc [&_ul]:pl-5"
    >
      {text ? (
        <Markdown
          remarkPlugins={[remarkGfm]}
          skipHtml
          urlTransform={safeUrl}
          components={components}
        >
          {linkCitations(text, sourceCount, anchorPrefix)}
        </Markdown>
      ) : state === "streaming" && placeholder ? (
        <p className="text-fg-muted">{placeholder}</p>
      ) : null}
      {state === "streaming" && text ? (
        <span aria-hidden className="animate-pulse">
          ▍
        </span>
      ) : null}
      {state === "interrupted" ? <p className="text-fg-muted">Stopped — not saved.</p> : null}
      {state === "error" ? (
        <p
          role="alert"
          className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-danger-fg"
        >
          {`${errorMessage ?? "Something went wrong."} Not saved.`}
        </p>
      ) : null}
    </div>
  );
}
