import type { components } from "@/api/schema";

type S = components["schemas"];

export type Digest = S["Digest"];
export type NightlyRun = S["NightlyRun"];
export type DigestIndexed = S["DigestIndexed"];
export type NightlyRunSummary = S["NightlyRunSummary"];
