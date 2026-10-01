import { useEffect, useState } from "react";
import { clearRecent, recentQueries, rememberQuery } from "./labels";

/** Recent searches; a query is saved only after it succeeded with its own (non-placeholder) data. */
export function useRememberQuery(
  q: string,
  search: { isSuccess: boolean; isPlaceholderData: boolean },
): { recent: string[]; clear: () => void } {
  const [recent, setRecent] = useState(recentQueries);
  const trimmed = q.trim();
  const ok = search.isSuccess && !search.isPlaceholderData;
  useEffect(() => {
    if (ok && trimmed) {
      rememberQuery(trimmed);
      setRecent(recentQueries());
    }
  }, [ok, trimmed]);
  return {
    recent,
    clear: () => {
      clearRecent();
      setRecent([]);
    },
  };
}
