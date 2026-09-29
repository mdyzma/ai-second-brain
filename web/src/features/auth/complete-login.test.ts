import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { completeLogin } from "./complete-login";
import { requireSession } from "./guard";
import { sessionQueryKey } from "./session";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ api: { GET: get } }));

const session = { authenticated: true, expires_at: "2026-10-13T00:00:00Z" };

describe("completeLogin", () => {
  beforeEach(() => {
    get.mockReset();
  });

  it("replaces a cached null session with a fresh one so the guard passes", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(sessionQueryKey, null); // cached by the first guard run
    get.mockResolvedValue({ data: session, response: { status: 200 } });

    await completeLogin(queryClient);

    expect(queryClient.getQueryData(sessionQueryKey)).toEqual(session);
    await expect(requireSession(queryClient, "/ask")).resolves.toBeUndefined();
  });

  it("does not throw when the session refetch fails", async () => {
    const queryClient = new QueryClient();
    get.mockImplementation(async () => {
      throw new Error("offline");
    });
    await completeLogin(queryClient);
    expect(queryClient.getQueryData(sessionQueryKey)).toBeUndefined();
  });
});
