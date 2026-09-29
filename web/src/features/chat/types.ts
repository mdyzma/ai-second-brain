import type { components } from "@/api/schema";

type Schemas = components["schemas"];

export type ChatMode = Schemas["ChatMode"];
export type ChatSession = Schemas["ChatSession"];
export type SessionDetail = Schemas["SessionDetail"];
export type Turn = Schemas["Turn"];
export type Source = Schemas["Source"];
export type ChatStatus = Schemas["ChatStatusResponse"];
export type StatusEvent = Schemas["StatusEvent"];
export type SourcesEvent = Schemas["SourcesEvent"];
export type TokenEvent = Schemas["TokenEvent"];
export type ReceiptEvent = Schemas["ReceiptEvent"];
export type DoneEvent = Schemas["DoneEvent"];
export type ErrorEvent = Schemas["ErrorEvent"];
export type TurnEvent =
  | StatusEvent
  | SourcesEvent
  | TokenEvent
  | ReceiptEvent
  | DoneEvent
  | ErrorEvent;
