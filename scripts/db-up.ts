import { compose, dockerAvailable, dockerHint } from "./lib/docker.ts";

if (!dockerAvailable()) {
  console.error(`Docker is not reachable. ${dockerHint()}`);
  process.exit(1);
}

const result = compose(["up", "-d", "--wait", "--wait-timeout", "60"]);
process.stdout.write(result.stdout ?? "");
process.stderr.write(result.stderr ?? "");
if (result.status !== 0) {
  console.error("Postgres did not become healthy. Inspect: docker compose -f infra/compose.yaml logs postgres");
  process.exit(result.status ?? 1);
}
console.log("Postgres is up (127.0.0.1:5433).");
