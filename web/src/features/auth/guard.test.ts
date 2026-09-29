import { QueryClient } from "@tanstack/react-query";
import { isRedirect } from "@tanstack/react-router";
import { describe, expect, it, vi } from "vitest";
import { requireSession } from "./guard";
import { sessionQueryKey } from "./session";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ api: { GET: get } }));

describe("requireSession", () => {
  it("treats a failed session fetch as no session and redirects to /login", async () => {
    get.mockRejectedValue(new Error("offline"));
    const error = await requireSession(new QueryClient(), "/ask").catch((e: unknown) => e);
    expect(isRedirect(error)).toBe(true);
    expect((error as { options: { to: string } }).options.to).toBe("/login");
  });

  it("throws a redirect to /login carrying the original location", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(sessionQueryKey, null);
    const error = await requireSession(queryClient, "/nodes?x=1").catch((e: unknown) => e);
    expect(isRedirect(error)).toBe(true);
    expect(
      (error as { options: { to: string; search: { redirect: string } } }).options,
    ).toMatchObject({
      to: "/login",
      search: { redirect: "/nodes?x=1" },
    });
  });

  it("resolves when a session exists", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(sessionQueryKey, {
      authenticated: true,
      expires_at: "2026-10-13T00:00:00Z",
    });
    await expect(requireSession(queryClient, "/ask")).resolves.toBeUndefined();
  });
});
