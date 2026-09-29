import type { ChatMode, ChatStatus, Turn, TurnState } from "./types";

export type TierDisplay =
  | { kind: "private"; endpoint: string; model: string; degraded: boolean }
  | { kind: "private-unavailable" }
  | { kind: "private-pending" }
  | { kind: "cloud" };

export function tierLabel(tier: TierDisplay): string {
  switch (tier.kind) {
    case "private":
      return tier.degraded
        ? `Private — small local model · ${tier.endpoint} (${tier.model})`
        : `Private · ${tier.endpoint} (${tier.model})`;
    case "private-unavailable":
      return "Private · no local model reachable";
    case "private-pending":
      return "Private";
    case "cloud":
      return "Cloud · Anthropic — messages leave your network";
  }
}

export function tierForSession(mode: ChatMode, status: ChatStatus | undefined): TierDisplay {
  if (mode === "cloud") return { kind: "cloud" };
  if (status === undefined) return { kind: "private-pending" };
  const endpoint = status.private.endpoints.find((e) => e.reachable);
  if (endpoint === undefined) return { kind: "private-unavailable" };
  return {
    kind: "private",
    endpoint: endpoint.label,
    model: endpoint.model,
    degraded: endpoint.degraded,
  };
}

export function tierForServed(served: NonNullable<TurnState["served"]>): TierDisplay {
  if (served.endpoint === "anthropic") return { kind: "cloud" };
  return { kind: "private", ...served };
}

export function tierForTurn(turn: Pick<Turn, "endpoint" | "model" | "degraded">): TierDisplay {
  return tierForServed({ endpoint: turn.endpoint, model: turn.model, degraded: turn.degraded });
}
