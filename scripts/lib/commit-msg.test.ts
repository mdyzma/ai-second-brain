import assert from "node:assert/strict";
import { test } from "node:test";
import { checkCommitMessage } from "./commit-msg.ts";

const ok = (message: string) => {
  const result = checkCommitMessage(message);
  assert.equal(result.ok, true, `expected ok for ${JSON.stringify(message)}: ${result.errors.join("; ")}`);
  return result;
};
const rejected = (message: string, pattern: RegExp) => {
  const result = checkCommitMessage(message);
  assert.equal(result.ok, false, `expected rejection for ${JSON.stringify(message)}`);
  assert.ok(result.errors.some((e) => pattern.test(e)), result.errors.join("; "));
};

test("accepts conventional headers with and without scope, body and footer", () => {
  ok("feat(web): add login page\n");
  ok("fix: handle empty cookie\n\nExplain why.\n\nCloses #12\n");
  ok("feat(api)!: drop v0 routes\n\nBREAKING CHANGE: /v0 removed\n");
  ok("chore(release): v0.2.0 [skip ci]\n");
  ok("ci: add Linux and macOS workflows\n");
});

test("rejects Co-Authored-By trailers in any case", () => {
  rejected("feat: x\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>\n", /attribution/i);
  rejected("feat: x\n\nco-authored-by: Someone <a@b.c>\n", /attribution/i);
});

test("rejects Claude Code attribution lines", () => {
  rejected("feat: x\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)\n", /attribution/i);
  rejected("feat: x\n\nGenerated with Claude Code\n", /attribution/i);
});

test("ignores git comment lines", () => {
  ok("feat: x\n# Co-Authored-By: this is only a comment\n");
});

test("rejects malformed headers", () => {
  rejected("Added login page\n", /type\(scope\): summary/);
  rejected("feature: add x\n", /type\(scope\): summary/);
  rejected("feat: add login page.\n", /period/);
  rejected(`feat: ${"x".repeat(70)}\n`, /hard limit is 72/);
  rejected("feat: x\nbody without blank line\n", /blank line/);
});

test("warns but accepts headers between 51 and 72 characters", () => {
  const result = ok("fix(web): clean biome output, check borders on surface\n");
  assert.ok(result.warnings.some((w) => /aim for ≤ 50/.test(w)));
});

test("exempts merge, revert and fixup commits from the header format", () => {
  ok("Merge branch 'x' into main\n");
  ok('Revert "feat: x"\n\nThis reverts commit abc.\n');
  ok("fixup! feat: x\n");
});

test("CRLF messages are handled", () => {
  ok("feat: x\r\n\r\nbody\r\n");
  rejected("feat: x\r\n\r\nCo-Authored-By: A <a@b.c>\r\n", /attribution/i);
});
