import { useCallback, useEffect, useState } from "react";
import { clearRecent, recentQueries, rememberQuery } from "./labels";

/** How long a successful query must stay unchanged before it counts as a search, not a prefix. */
export const STABLE_MS = 2000;

/**
 * Recent searches. A query is saved when the caller says so (Enter, a result click) or once it
 * has stayed unchanged for STABLE_MS after a successful (non-placeholder) response, so
 * debounced prefixes typed past are never saved.
 */
export function useRememberQuery(
  q: string,
  search: { isSuccess: boolean; isPlaceholderData: boolean },
): { recent: string[]; clear: () => void; remember: (q: string) => void } {
  const [recent, setRecent] = useState(recentQueries);
  const remember = useCallback((query: string) => {
    const trimmed = query.trim();
    if (!trimmed) return;
    rememberQuery(trimmed);
    setRecent(recentQueries());
  }, []);
  const trimmed = q.trim();
  const ok = search.isSuccess && !search.isPlaceholderData;
  useEffect(() => {
    if (!ok || !trimmed) return;
    const timer = setTimeout(() => remember(trimmed), STABLE_MS);
    return () => clearTimeout(timer);
  }, [ok, trimmed, remember]);
  return {
    recent,
    remember,
    clear: () => {
      clearRecent();
      setRecent([]);
    },
  };
}
