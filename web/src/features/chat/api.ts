import { queryOptions } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { ChatMode, ChatSession } from "./types";

export const chatKeys = {
  sessions: ["chat", "sessions"] as const,
  session: (id: string) => ["chat", "session", id] as const,
  status: ["chat", "status"] as const,
};

export const sessionsQueryOptions = queryOptions({
  queryKey: chatKeys.sessions,
  queryFn: async () => {
    const { data, response } = await api.GET("/api/sessions");
    if (!data) throw new Error(`Listing conversations failed with status ${response.status}`);
    return data;
  },
});

export function chatSessionQueryOptions(id: string) {
  return queryOptions({
    queryKey: chatKeys.session(id),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/sessions/{session_id}", {
        params: { path: { session_id: id } },
      });
      if (response.status === 404 || response.status === 422) return null;
      if (!data) throw new Error(`Loading the conversation failed with status ${response.status}`);
      return data;
    },
  });
}

export const chatStatusQueryOptions = queryOptions({
  queryKey: chatKeys.status,
  queryFn: async () => {
    const { data, response } = await api.GET("/api/chat/status");
    if (!data) throw new Error(`Chat status failed with status ${response.status}`);
    return data;
  },
  refetchInterval: 30_000,
  staleTime: 10_000,
});

export type CreateResult = { ok: true; session: ChatSession } | { ok: false; message: string };

export async function createSession(mode: ChatMode): Promise<CreateResult> {
  try {
    const { data, response } = await api.POST("/api/sessions", { body: { mode } });
    if (data) return { ok: true, session: data };
    if (response.status === 409) return { ok: false, message: "Cloud mode is not configured." };
    return { ok: false, message: "Couldn't start the conversation. Try again." };
  } catch {
    return { ok: false, message: "Can't reach the server." };
  }
}

export async function deleteSession(id: string): Promise<boolean> {
  try {
    const { response } = await api.DELETE("/api/sessions/{session_id}", {
      params: { path: { session_id: id } },
    });
    return response.status === 204 || response.status === 404;
  } catch {
    return false;
  }
}
