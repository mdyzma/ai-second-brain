import { queryOptions } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";

export type SessionInfo = components["schemas"]["MeResponse"];
export const sessionQueryKey = ["auth", "session"] as const;

export async function fetchSession(): Promise<SessionInfo | null> {
  const { data, response } = await api.GET("/api/auth/me");
  if (response.status === 401) return null;
  if (!data) throw new Error(`Session check failed with status ${response.status}`);
  return data;
}

export const sessionQueryOptions = queryOptions({
  queryKey: sessionQueryKey,
  queryFn: fetchSession,
  staleTime: 60_000,
  retry: false,
});

export type LoginResult =
  | { ok: true }
  | { ok: false; reason: "invalid" }
  | { ok: false; reason: "throttled"; retryAfter: number }
  | { ok: false; reason: "unreachable" };

export function interpretLoginResponse(status: number, retryAfter: string | null): LoginResult {
  if (status === 204) return { ok: true };
  if (status === 401 || status === 422) return { ok: false, reason: "invalid" };
  if (status === 429) {
    const seconds = Number.parseInt(retryAfter ?? "", 10);
    return {
      ok: false,
      reason: "throttled",
      retryAfter: Number.isFinite(seconds) && seconds > 0 ? seconds : 60,
    };
  }
  return { ok: false, reason: "unreachable" };
}

export async function login(password: string): Promise<LoginResult> {
  try {
    const { response } = await api.POST("/api/auth/login", { body: { password } });
    return interpretLoginResponse(response.status, response.headers.get("Retry-After"));
  } catch {
    return { ok: false, reason: "unreachable" };
  }
}

export async function logout(): Promise<void> {
  try {
    await api.POST("/api/auth/logout");
  } catch {
    // Logging out while offline still clears local state; the cookie expires server-side.
  }
}

/** Only same-app relative paths are allowed as post-login destinations (no open redirects). */
export function safeRedirect(target: unknown): string {
  if (typeof target !== "string") return "/ask";
  if (!target.startsWith("/") || target.startsWith("//") || target.startsWith("/\\")) return "/ask";
  if (target === "/login" || target.startsWith("/login?") || target.startsWith("/login/"))
    return "/ask";
  return target;
}
