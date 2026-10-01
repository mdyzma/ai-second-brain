import { UNREACHABLE } from "@/features/sources/labels";

/** Plain-language text for a failed capture; never shows server text. Status 0 = network failure. */
export function captureErrorCopy(status: number, detail?: string): string {
  if (detail === "vault_disabled") return "No vault is configured. Set SB_VAULT_PATH.";
  if (detail === "vault_unwritable") return "Couldn't write to the vault folder.";
  if (detail === "capture_name_taken") return "Too many captures with this title this minute.";
  if (status === 0) return UNREACHABLE;
  return "Couldn't save the note. Try again.";
}
