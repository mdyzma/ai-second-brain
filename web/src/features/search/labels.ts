import { DB_DOWN, SESSION_ENDED, UNREACHABLE } from "@/features/sources/labels";

const ENTITIES: Record<string, string> = {
  "&lt;": "<",
  "&gt;": ">",
  "&amp;": "&",
  "&quot;": '"',
  "&#39;": "'",
};
const decode = (s: string) => s.replace(/&(lt|gt|amp|quot|#39);/g, (m) => ENTITIES[m] ?? m);

/** Server snippets are escaped text with only <mark>…</mark>; anything else stays literal text. */
export function snippetParts(snippet: string): { text: string; mark: boolean }[] {
  const parts: { text: string; mark: boolean }[] = [];
  const re = /<mark>(.*?)<\/mark>/gs;
  let last = 0;
  for (const m of snippet.matchAll(re)) {
    if (m.index > last) parts.push({ text: decode(snippet.slice(last, m.index)), mark: false });
    parts.push({ text: decode(m[1] ?? ""), mark: true });
    last = m.index + m[0].length;
  }
  if (last < snippet.length) parts.push({ text: decode(snippet.slice(last)), mark: false });
  return parts.filter((p) => p.text.length > 0);
}

export const VECTOR_UNAVAILABLE =
  "Matching by meaning is unavailable right now; showing exact text matches.";

export function errorCopy(status: number, detail?: string): string {
  if (status === 409 && detail === "vault_disabled")
    return "Set SB_VAULT_PATH to search your notes.";
  if (status === 503) return DB_DOWN;
  if (status === 401) return SESSION_ENDED;
  if (status === 0) return UNREACHABLE;
  return "Search failed. Try again.";
}

const RECENT_KEY = "sb.search.recent";
export function recentQueries(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const list: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(list)
      ? list.filter((x): x is string => typeof x === "string").slice(0, 10)
      : [];
  } catch {
    return [];
  }
}
export function rememberQuery(q: string): void {
  try {
    const next = [q, ...recentQueries().filter((x) => x !== q)].slice(0, 10);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable: recent searches are a convenience */
  }
}
export function clearRecent(): void {
  try {
    localStorage.removeItem(RECENT_KEY);
  } catch {
    /* ignore */
  }
}
