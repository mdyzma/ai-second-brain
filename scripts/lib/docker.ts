import { type SpawnSyncReturns, spawnSync } from "node:child_process";
import { platform } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
export const composeFile = join(repoRoot, "infra", "compose.yaml");

export function docker(args: string[]): SpawnSyncReturns<string> {
  return spawnSync("docker", args, { encoding: "utf8" });
}

export function compose(args: string[]): SpawnSyncReturns<string> {
  return docker(["compose", "-f", composeFile, ...args]);
}

/** True when the docker CLI exists and the daemon answers. */
export function dockerAvailable(): boolean {
  const result = docker(["info", "--format", "{{.ServerVersion}}"]);
  return result.error === undefined && result.status === 0;
}

export function dockerHint(os: NodeJS.Platform = platform()): string {
  switch (os) {
    case "win32":
      return "Start Docker Desktop and wait until it reports 'Engine running'.";
    case "darwin":
      return "Start Docker Desktop or OrbStack, then retry.";
    default:
      return "Start the Docker service (e.g. `sudo systemctl start docker`), then retry.";
  }
}
