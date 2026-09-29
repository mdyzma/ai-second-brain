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

const CITATION = /\[(\d{1,3})\]/g;

type MdNode = { type: string; value?: string; url?: string; children?: MdNode[] };

const SKIP = new Set(["inlineCode", "code", "link", "linkReference", "definition", "html"]);

/** Split one text node into text and link nodes for the citations that name a real source. */
function linkifyText(value: string, count: number, anchorPrefix: string): MdNode[] {
  const out: MdNode[] = [];
  let last = 0;
  for (const match of value.matchAll(CITATION)) {
    const n = Number(match[1]);
    if (n < 1 || n > count) continue;
    const at = match.index ?? 0;
    if (at > last) out.push({ type: "text", value: value.slice(last, at) });
    out.push({
      type: "link",
      url: `#${anchorPrefix}-source-${n}`,
      children: [{ type: "text", value: match[0] }],
    });
    last = at + match[0].length;
  }
  if (last === 0) return [{ type: "text", value }];
  if (last < value.length) out.push({ type: "text", value: value.slice(last) });
  return out;
}

function walk(node: MdNode, count: number, anchorPrefix: string): void {
  if (SKIP.has(node.type) || node.children === undefined) return;
  node.children = node.children.flatMap((child) => {
    if (child.type === "text" && child.value !== undefined)
      return linkifyText(child.value, count, anchorPrefix);
    walk(child, count, anchorPrefix);
    return [child];
  });
}

/** Turn "[n]" in normal text (never code, never existing links) into a link to source n. */
export function remarkCitations(count: number, anchorPrefix: string) {
  return (tree: MdNode): void => walk(tree, count, anchorPrefix);
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
  // Never render images: a remote src would be fetched with no click (egress).
  img: ({ alt }) => (alt ? <span>{alt}</span> : null),
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
          remarkPlugins={[remarkGfm, [remarkCitations, sourceCount, anchorPrefix]]}
          skipHtml
          urlTransform={safeUrl}
          components={components}
        >
          {text}
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
