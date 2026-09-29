export type CommitCheck = { ok: boolean; errors: string[]; warnings: string[] };

const TYPES = ["feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert"];
const HEADER = new RegExp(`^(${TYPES.join("|")})(\\([a-z0-9._/-]+\\))?!?: \\S`);
const EXEMPT = /^(Merge |Revert "|fixup! |squash! |amend! )/;
const ATTRIBUTION = [
  /^\s*co-authored-by:/im,
  /generated with \[?claude/i,
  /noreply@anthropic\.com/i,
  /\u{1F916}/u,
];

/** Validate a commit message: no AI attribution, Conventional Commits header. */
export function checkCommitMessage(raw: string): CommitCheck {
  const lines = raw
    .replace(/\r\n/g, "\n")
    .split("\n")
    .filter((line) => !line.startsWith("#"));
  const message = lines.join("\n").trim();
  const errors: string[] = [];
  const warnings: string[] = [];

  if (ATTRIBUTION.some((pattern) => pattern.test(message))) {
    errors.push("AI attribution (Co-Authored-By / 'Generated with Claude') is not allowed. Remove it.");
  }

  const [header = "", second] = message.split("\n");
  if (!EXEMPT.test(header)) {
    if (!HEADER.test(header)) {
      errors.push(`Header must be "type(scope): summary" with type one of: ${TYPES.join(", ")}.`);
    }
    if (header.endsWith(".")) errors.push("Header must not end with a period.");
    if (header.length > 72) {
      errors.push(`Header is ${header.length} characters; the hard limit is 72.`);
    } else if (header.length > 50) {
      warnings.push(`Header is ${header.length} characters; aim for ≤ 50.`);
    }
  }
  if (second !== undefined && second !== "") errors.push("Leave a blank line after the header.");

  return { ok: errors.length === 0, errors, warnings };
}
