import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/features/sources/api";

const post = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ api: { POST: post, GET: vi.fn() } }));

import {
  DIGEST_POLL_FAST_MS,
  DIGEST_POLL_SLOW_MS,
  digestKeys,
  digestPollInterval,
  startRun,
} from "./api";

const withStatus = (status: "running" | "complete" | "failed") =>
  ({ run: { status } }) as Parameters<typeof digestPollInterval>[0];

describe("digestPollInterval", () => {
  it("is fast while the run is running", () => {
    expect(digestPollInterval(withStatus("running"))).toBe(DIGEST_POLL_FAST_MS);
    expect(DIGEST_POLL_FAST_MS).toBe(5_000);
  });
  it("is slow otherwise", () => {
    expect(digestPollInterval(withStatus("complete"))).toBe(DIGEST_POLL_SLOW_MS);
    expect(digestPollInterval(withStatus("failed"))).toBe(DIGEST_POLL_SLOW_MS);
    expect(digestPollInterval(undefined)).toBe(DIGEST_POLL_SLOW_MS);
    expect(DIGEST_POLL_SLOW_MS).toBe(60_000);
  });
});

describe("digestKeys", () => {
  it("nests every digest key under all", () => {
    expect(digestKeys.all).toEqual(["digest"]);
    expect(digestKeys.latest).toEqual(["digest", "latest"]);
    expect(digestKeys.byRun("r1")).toEqual(["digest", "run", "r1"]);
    expect(digestKeys.runs).toEqual(["digest", "runs"]);
  });
});

describe("startRun", () => {
  beforeEach(() => post.mockReset());

  it("invalidates the digest after a run starts", async () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries").mockResolvedValue();
    post.mockResolvedValue({ data: { run: { id: "r1" } }, response: { status: 202 } });
    await startRun(qc);
    expect(post).toHaveBeenCalledWith("/api/nightly/run");
    expect(spy).toHaveBeenCalledWith({ queryKey: digestKeys.all });
  });

  it("refreshes the digest and rejects with HttpError(409) when a run is busy", async () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries").mockResolvedValue();
    post.mockResolvedValue({
      data: undefined,
      error: { detail: "nightly_busy" },
      response: { status: 409 },
    });
    const error = await startRun(qc).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(HttpError);
    expect((error as HttpError).status).toBe(409);
    expect(spy).toHaveBeenCalledWith({ queryKey: digestKeys.all });
  });

  it("does not refresh on other errors", async () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries").mockResolvedValue();
    post.mockResolvedValue({ data: undefined, response: { status: 503 } });
    const error = await startRun(qc).catch((e: unknown) => e);
    expect((error as HttpError).status).toBe(503);
    expect(spy).not.toHaveBeenCalled();
  });
});
