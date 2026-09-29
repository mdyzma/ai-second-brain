// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import * as client from "@/api/client";
import {
  isFinished,
  REQUEST_ERRORS,
  startTurn,
  streamTurn,
  type TurnAction,
  toTurnEvent,
  turnReducer,
} from "./turn";
import type { TurnEvent } from "./types";

const RECEIPT: TurnEvent = {
  event: "receipt",
  turn_id: "00000000-0000-4000-8000-000000000001",
  seq: 1,
  endpoint: "ws",
  model: "m",
  degraded: false,
  duration_ms: 5,
};

function sseBody(frames: string[]): Response {
  return new Response(frames.join(""), {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

function frame(event: TurnEvent): string {
  return `event: ${event.event}\ndata: ${JSON.stringify(event)}\n\n`;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("turnReducer", () => {
  it("walks retrieving → generating → done", () => {
    let state = startTurn("Q");
    const events: TurnEvent[] = [
      { event: "sources", items: [], disabled: false },
      { event: "status", phase: "connecting", endpoint: null, model: null, degraded: null },
      { event: "status", phase: "generating", endpoint: "cpu", model: "m", degraded: true },
      { event: "token", text: "Hel" },
      { event: "token", text: "lo" },
      RECEIPT,
      { event: "done" },
    ];
    for (const event of events) state = turnReducer(state, { type: "event", event });
    expect(state.phase).toBe("done");
    expect(state.answer).toBe("Hello");
    expect(state.sources).toEqual([]);
    expect(state.served).toEqual({ endpoint: "cpu", model: "m", degraded: true });
    expect(state.receipt).toEqual(RECEIPT);
    expect(isFinished(state)).toBe(true);
  });

  it("ignores everything after a terminal state", () => {
    const stopped = turnReducer(startTurn("Q"), { type: "interrupted" });
    const later = turnReducer(stopped, { type: "event", event: { event: "token", text: "x" } });
    expect(later).toBe(stopped);
  });

  it("records server errors", () => {
    const state = turnReducer(startTurn("Q"), {
      type: "event",
      event: { event: "error", code: "no_local_model", component: "ollama", message: "M" },
    });
    expect(state.phase).toBe("error");
    expect(state.error).toEqual({ code: "no_local_model", message: "M" });
  });
});

describe("toTurnEvent", () => {
  it("rejects unknown names, bad JSON and mismatched payloads", () => {
    expect(toTurnEvent({ event: "mystery", data: "{}" })).toBeNull();
    expect(toTurnEvent({ event: "token", data: "{not json" })).toBeNull();
    expect(toTurnEvent({ event: "token", data: '{"event":"done"}' })).toBeNull();
    expect(toTurnEvent({ event: "done", data: '{"event":"done"}' })).toEqual({ event: "done" });
  });
});

describe("streamTurn", () => {
  async function run(response: Response | Error, abort = false): Promise<TurnAction[]> {
    const actions: TurnAction[] = [];
    const controller = new AbortController();
    if (abort) controller.abort();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        if (response instanceof Error) throw response;
        return response;
      }),
    );
    await streamTurn("s1", "Q", controller.signal, (action) => actions.push(action));
    return actions;
  }

  it("dispatches each event in order", async () => {
    const actions = await run(
      sseBody([frame({ event: "token", text: "a" }), frame({ event: "done" })]),
    );
    expect(actions.map((a) => (a.type === "event" ? a.event.event : a.type))).toEqual([
      "token",
      "done",
    ]);
  });

  it("409 maps to turn_in_progress", async () => {
    const actions = await run(new Response('{"detail":"turn_in_progress"}', { status: 409 }));
    expect(actions).toEqual([
      { type: "failed", code: "turn_in_progress", message: REQUEST_ERRORS.turn_in_progress },
    ]);
  });

  it("maps 404, 422 and network errors", async () => {
    expect((await run(new Response("", { status: 404 })))[0]).toMatchObject({ code: "not_found" });
    expect((await run(new Response("", { status: 422 })))[0]).toMatchObject({ code: "invalid" });
    expect((await run(new TypeError("offline")))[0]).toMatchObject({ code: "unreachable" });
  });

  it("reports 401 to the unauthorized handler", async () => {
    const spy = vi.spyOn(client, "notifyUnauthorized");
    await run(new Response("", { status: 401 }));
    expect(spy).toHaveBeenCalledOnce();
  });

  it("an aborted request is interrupted, not failed", async () => {
    const actions = await run(new DOMException("aborted", "AbortError"), true);
    expect(actions).toEqual([{ type: "interrupted" }]);
  });

  it("a stream that ends without done is incomplete", async () => {
    const actions = await run(sseBody([frame({ event: "token", text: "a" })]));
    expect(actions.at(-1)).toEqual({
      type: "failed",
      code: "incomplete",
      message: REQUEST_ERRORS.incomplete,
    });
  });
});
