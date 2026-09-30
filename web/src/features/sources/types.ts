import type { components } from "@/api/schema";

type S = components["schemas"];
export type SourcesSummary = S["SourcesSummary"];
export type SourceRow = S["SourceRow"];
export type SourceList = S["SourceList"];
export type StateFilter = "pending" | "indexed" | "failed" | "deleted" | null;
export type Filters = { state: StateFilter; q: string };
