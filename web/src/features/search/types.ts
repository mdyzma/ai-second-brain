import type { components } from "@/api/schema";

type S = components["schemas"];
export type SearchResponse = S["SearchResponse"];
export type SearchHit = S["SearchHit"];
export type SearchFacets = S["SearchFacets"];
