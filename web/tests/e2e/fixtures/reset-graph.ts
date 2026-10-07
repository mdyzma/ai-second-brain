import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseEnv } from "node:util";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");

// Clears extraction results (not the indexed notes) so specs sharing the e2e database start clean.
// `just` loads the developer's .env into this process, so DATABASE_URL must be pinned to the
// test database explicitly, never inherited.
export function resetGraph(): void {
  const testEnv = parseEnv(readFileSync(join(root, ".env.test"), "utf8"));
  const url = testEnv.TEST_DATABASE_URL;
  if (!url || !/_test\b/.test(url)) throw new Error("refusing to reset: not a test database URL");
  execFileSync(
    "uv",
    ["run", "--directory", "../backend", "python", "tests/e2e_reset.py", "--graph"],
    {
      stdio: "inherit",
      env: { PATH: process.env.PATH, SystemRoot: process.env.SystemRoot, DATABASE_URL: url },
    },
  );
}
