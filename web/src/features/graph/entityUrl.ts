import { ENTITY_TYPES } from "./labels";
import type { EntityType } from "./types";

export type EntitiesState = { type?: EntityType; q: string };

export function parseEntitiesSearch(raw: Record<string, unknown>): EntitiesState {
  const q = typeof raw.q === "string" ? raw.q : "";
  const type = ENTITY_TYPES.find((t) => t === raw.type);
  return type ? { type, q } : { q };
}

export function toEntitiesParams(state: EntitiesState): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (state.type) out.type = state.type;
  if (state.q) out.q = state.q;
  return out;
}
