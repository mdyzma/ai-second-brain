import { describe, expect, it } from "vitest";
import { tierForSession, tierForTurn, tierLabel } from "./tier";
import type { ChatStatus, Turn } from "./types";

const STATUS: ChatStatus = {
  private: {
    available: true,
    endpoints: [
      { label: "gpu", model: "big", degraded: false, reachable: false },
      { label: "cpu", model: "small", degraded: true, reachable: true },
    ],
  },
  cloud: { available: false, model: null },
};

describe("tier", () => {
  it("labels every tier in words", () => {
    expect(tierLabel({ kind: "private", endpoint: "gpu", model: "big", degraded: false })).toBe(
      "Private · gpu (big)",
    );
    expect(tierLabel({ kind: "private", endpoint: "cpu", model: "small", degraded: true })).toBe(
      "Private — small local model · cpu (small)",
    );
    expect(tierLabel({ kind: "private-unavailable" })).toBe("Private · no local model reachable");
    expect(tierLabel({ kind: "private-pending" })).toBe("Private");
    expect(tierLabel({ kind: "cloud" })).toBe("Cloud · Anthropic — messages leave your network");
  });

  it("derives a private session's tier from the first reachable endpoint", () => {
    expect(tierForSession("private", STATUS)).toEqual({
      kind: "private",
      endpoint: "cpu",
      model: "small",
      degraded: true,
    });
    expect(tierForSession("private", undefined)).toEqual({ kind: "private-pending" });
    const none = { ...STATUS, private: { available: false, endpoints: [] } };
    expect(tierForSession("private", none)).toEqual({ kind: "private-unavailable" });
    expect(tierForSession("cloud", STATUS)).toEqual({ kind: "cloud" });
  });

  it("uses what actually served a saved turn", () => {
    const turn = { endpoint: "anthropic", model: "claude", degraded: false } as Turn;
    expect(tierForTurn(turn)).toEqual({ kind: "cloud" });
    const local = { endpoint: "gpu", model: "big", degraded: false } as Turn;
    expect(tierForTurn(local)).toEqual({
      kind: "private",
      endpoint: "gpu",
      model: "big",
      degraded: false,
    });
  });
});
