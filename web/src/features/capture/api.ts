import { api } from "@/api/client";
import { detailOf } from "@/features/sources/api";

export type Captured = { path: string; title: string; obsidian_url: string | null };
export type CaptureResult =
  | ({ ok: true } & Captured)
  | { ok: false; status: number; detail?: string | undefined };

export async function captureNote(text: string): Promise<CaptureResult> {
  try {
    const { data, error, response } = await api.POST("/api/capture", { body: { text } });
    if (data) {
      return {
        ok: true,
        path: data.path,
        title: data.title,
        obsidian_url: data.obsidian_url ?? null,
      };
    }
    return { ok: false, status: response.status, detail: detailOf(error) };
  } catch {
    return { ok: false, status: 0 };
  }
}
