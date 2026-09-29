import { copyFileSync, existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { parseEnv } from "node:util";
import { repoRoot } from "./lib/docker.ts";

const envPath = join(repoRoot, ".env");
const examplePath = join(repoRoot, ".env.example");

if (!existsSync(envPath)) {
  copyFileSync(examplePath, envPath);
  console.log("Created .env from .env.example.");
} else {
  const current = parseEnv(readFileSync(envPath, "utf8"));
  const expected = Object.keys(parseEnv(readFileSync(examplePath, "utf8")));
  const missing = expected.filter((key) => !(key in current));
  if (missing.length > 0) {
    console.warn(`.env is missing: ${missing.join(", ")}. Copy them from .env.example.`);
  }
}
