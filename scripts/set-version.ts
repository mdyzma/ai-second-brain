import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { repoRoot } from "./lib/docker.ts";
import { assertSemver, setPackageJsonVersion, setPyprojectVersion } from "./lib/version.ts";

const version = process.argv[2] ?? "";
assertSemver(version);

function edit(relativePath: string, update: (text: string, version: string) => string): void {
  const path = join(repoRoot, relativePath);
  writeFileSync(path, update(readFileSync(path, "utf8"), version), "utf8");
}

edit("backend/pyproject.toml", setPyprojectVersion);
edit("web/package.json", setPackageJsonVersion);

const lock = spawnSync("uv", ["lock", "--directory", join(repoRoot, "backend")], { stdio: "inherit" });
if (lock.status !== 0) process.exit(lock.status ?? 1);
console.log(`Version set to ${version}`);
