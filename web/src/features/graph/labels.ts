import { DB_DOWN, SESSION_ENDED, UNREACHABLE } from "@/features/sources/labels";
import type { EntityType, Relation } from "./types";

/** Forward and reverse wording for each relation. */
export const RELATION_LABEL: Record<Relation, [string, string]> = {
  runs_on: ["runs on", "runs"],
  uses: ["uses", "used by"],
  works_with: ["works with", "works with"],
  part_of: ["part of", "contains"],
  about: ["about", "discussed in"],
  mentions: ["mentions", "mentioned in"],
};

export const ENTITY_TYPES: EntityType[] = [
  "project",
  "person",
  "organization",
  "tool",
  "device",
  "topic",
];

export const TYPE_LABEL: Record<EntityType, string> = {
  project: "Project",
  person: "Person",
  organization: "Organization",
  tool: "Tool",
  device: "Device",
  topic: "Topic",
};

export const BUSY = "Someone else is changing the graph right now. Try again.";
export const NO_MODEL = "No local model is configured for extraction.";

/** Plain-language text for a failed entity decision; never shows server text. Status 0 = network failure. */
export function entityErrorCopy(status: number, detail?: string, type: string = "entity"): string {
  if (status === 401) return SESSION_ENDED;
  if (status === 503) return DB_DOWN;
  if (status === 0) return UNREACHABLE;
  if (status === 404) return "That entity is no longer in the review queue.";
  if (status === 409) {
    if (detail === "name_taken")
      return `Another ${type.toLowerCase()} already has this name — merge instead?`;
    if (detail === "busy") return BUSY;
    return "That change conflicts with the current graph. Try again.";
  }
  if (status === 422) {
    if (detail === "parent_cycle") return "That would make a loop.";
    if (detail === "type_mismatch") return "Only entities of the same type can be merged.";
    return "That change isn't allowed.";
  }
  return "Couldn't save that change. Try again.";
}

export function linksErrorCopy(status: number): string {
  if (status === 401) return SESSION_ENDED;
  if (status === 503) return DB_DOWN;
  if (status === 0) return UNREACHABLE;
  if (status === 409) return BUSY;
  return "Couldn't save those decisions. Try again.";
}

export function extractErrorCopy(status: number, detail?: string): string {
  if (status === 401) return SESSION_ENDED;
  if (status === 503) return DB_DOWN;
  if (status === 0) return UNREACHABLE;
  if (status === 409 && detail === "extraction_unavailable") return NO_MODEL;
  if (status === 403) return "That request was refused. Reload the page and try again.";
  return "Couldn't start the extraction. Try again.";
}

export function loadErrorCopy(status: number): string {
  if (status === 401) return SESSION_ENDED;
  if (status === 503) return DB_DOWN;
  if (status === 0) return UNREACHABLE;
  return "Couldn't load the review queue.";
}

export function queuedCopy(n: number): string {
  return `Queued ${n} ${n === 1 ? "note" : "notes"} for extraction.`;
}
