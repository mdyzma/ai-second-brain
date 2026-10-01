import { beforeEach, describe, expect, it } from "vitest";
import { DB_DOWN, SESSION_ENDED, UNREACHABLE } from "@/features/sources/labels";
import { clearRecent, errorCopy, recentQueries, rememberQuery, snippetParts } from "./labels";

describe("snippetParts", () => {
  it("splits marks and decodes entities", () => {
    expect(snippetParts("a <mark>b</mark> &lt;c&gt; &amp;")).toEqual([
      { text: "a ", mark: false },
      { text: "b", mark: true },
      { text: " <c> &", mark: false },
    ]);
  });
  it("renders a script tag in a snippet as text", () => {
    expect(snippetParts("<script>x</script>")).toEqual([
      { text: "<script>x</script>", mark: false },
    ]);
  });
});

describe("errorCopy", () => {
  it("maps codes, sharing the Sources copy", () => {
    expect(errorCopy(409, "vault_disabled")).toBe("Set SB_VAULT_PATH to search your notes.");
    expect(errorCopy(503)).toBe(DB_DOWN);
    expect(errorCopy(401)).toBe(SESSION_ENDED);
    expect(errorCopy(0)).toBe(UNREACHABLE);
    expect(errorCopy(503)).toBe("The database is unavailable. Try again in a moment.");
    expect(errorCopy(0)).toBe("Can't reach the server.");
    expect(errorCopy(500)).toBe("Search failed. Try again.");
  });
});

describe("recent queries", () => {
  beforeEach(() => localStorage.clear());
  it("remembers most recent first without duplicates, and clears", () => {
    rememberQuery("a");
    rememberQuery("b");
    rememberQuery("a");
    expect(recentQueries()).toEqual(["a", "b"]);
    clearRecent();
    expect(recentQueries()).toEqual([]);
  });
  it("tolerates corrupt storage", () => {
    localStorage.setItem("sb.search.recent", "{oops");
    expect(recentQueries()).toEqual([]);
  });
});
