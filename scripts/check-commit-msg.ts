import { readFileSync } from "node:fs";
import { checkCommitMessage } from "./lib/commit-msg.ts";

const path = process.argv[2];
if (!path) {
  console.error("usage: check-commit-msg <commit-message-file>");
  process.exit(2);
}
const result = checkCommitMessage(readFileSync(path, "utf8"));
for (const warning of result.warnings) console.warn(`commit-msg: warning: ${warning}`);
if (!result.ok) {
  for (const error of result.errors) console.error(`commit-msg: ${error}`);
  console.error("Commit rejected. Format: type(scope): summary (see README > Commit messages).");
  process.exit(1);
}
