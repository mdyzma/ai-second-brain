const OBSIDIAN_URL = /^obsidian:\/\//;

/** Only obsidian:// links may be rendered as hrefs; anything else (javascript:, http:) is dropped. */
export function isObsidianUrl(url: string | null | undefined): url is string {
  return typeof url === "string" && OBSIDIAN_URL.test(url);
}
