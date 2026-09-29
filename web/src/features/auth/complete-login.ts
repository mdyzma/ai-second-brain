import type { QueryClient } from "@tanstack/react-query";
import { sessionQueryOptions } from "./session";

/**
 * Get a fresh session after a successful login. The guards may have cached `null` before the
 * login, and `ensureQueryData` treats that as fresh data, so the cache must be refreshed here
 * (an invalidate would not refetch because nothing observes the key).
 */
export async function completeLogin(queryClient: QueryClient): Promise<void> {
  try {
    await queryClient.fetchQuery({ ...sessionQueryOptions, staleTime: 0 });
  } catch {
    // Leave the cache alone: the guard treats a missing or failed session as "not signed in".
  }
}
