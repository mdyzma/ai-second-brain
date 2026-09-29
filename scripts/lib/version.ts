const SEMVER = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/;

export function assertSemver(version: string): void {
  if (!SEMVER.test(version)) throw new Error(`Not a SemVer version: "${version}"`);
}

/** Replace `version = "..."` inside the [project] table only. */
export function setPyprojectVersion(toml: string, version: string): string {
  assertSemver(version);
  let inProject = false;
  let replaced = false;
  const lines = toml.split("\n").map((line) => {
    const table = /^\s*\[([^\]]+)\]\s*$/.exec(line);
    if (table) {
      inProject = table[1] === "project";
      return line;
    }
    if (inProject && !replaced && /^\s*version\s*=/.test(line)) {
      replaced = true;
      return `version = "${version}"`;
    }
    return line;
  });
  if (!replaced) throw new Error("pyproject.toml has no [project] version");
  return lines.join("\n");
}

/** Set "version" (placed right after "name"), keeping other keys and 2-space formatting. */
export function setPackageJsonVersion(json: string, version: string): string {
  assertSemver(version);
  const { name, version: _previous, ...rest } = JSON.parse(json) as Record<string, unknown>;
  return `${JSON.stringify({ name, version, ...rest }, null, 2)}\n`;
}
