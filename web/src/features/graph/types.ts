import type { components } from "@/api/schema";

type S = components["schemas"];
export type GraphStatus = S["GraphStatus"];
export type ReviewEntity = S["ReviewEntity"];
export type ReviewLink = S["ReviewLink"];
export type EntitySummary = S["EntitySummary"];
export type EntityDecision = S["EntityDecision"];
export type LinkDecision = S["LinkDecision"];
export type EntityType = ReviewEntity["type"];
export type Relation = ReviewLink["relation"];
export type ExtractScope = S["GraphExtractRequest"]["scope"];
