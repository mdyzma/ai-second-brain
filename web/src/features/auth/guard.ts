import type { QueryClient } from "@tanstack/react-query";
import { redirect } from "@tanstack/react-router";
import { sessionQueryOptions } from "./session";

/** Throws a redirect to /login unless a session exists. Errors count as "no session". */
export async function requireSession(queryClient: QueryClient, href: string): Promise<void> {
  const session = await queryClient
    .ensureQueryData({ ...sessionQueryOptions, revalidateIfStale: true })
    .catch(() => null);
  if (!session) throw redirect({ to: "/login", search: { redirect: href } });
}
