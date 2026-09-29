import { describe, expect, it, vi } from "vitest";
import { setUnauthorizedHandler, unauthorizedMiddleware } from "./client";

async function respond(path: string, status: number): Promise<void> {
  const request = new Request(`http://localhost${path}`);
  const response = new Response(null, { status });
  // biome-ignore lint/suspicious/noExplicitAny: middleware params are library-internal
  await unauthorizedMiddleware.onResponse?.({ request, response } as any);
}

describe("unauthorizedMiddleware", () => {
  it("calls the handler on 401 from ordinary endpoints", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await respond("/api/search", 401);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it.each(["/api/auth/me", "/api/auth/login"])("ignores 401 from %s", async (path) => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await respond(path, 401);
    expect(handler).not.toHaveBeenCalled();
  });

  it("ignores other statuses", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await respond("/api/search", 500);
    expect(handler).not.toHaveBeenCalled();
  });
});
