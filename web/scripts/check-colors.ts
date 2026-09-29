import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export type Violation = { line: number; text: string };

const PATTERNS = [
  /(?<![\w&/])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])/,
  /\b(?:rgba?|hsla?|oklch|oklab|lch|lab|hwb)\(/,
  /-\[(?:#|rgb|hsl|oklch|color:)/,
];
const SKIP_FILES = new Set(["tokens.css", "routeTree.gen.ts"]);

export function findViolations(source: string): Violation[] {
  return source
    .split(/\r?\n/)
    .flatMap((text, index) =>
      PATTERNS.some((pattern) => pattern.test(text))
        ? [{ line: index + 1, text: text.trim() }]
        : [],
    );
}

function* walk(dir: string): Generator<string> {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== "api") yield* walk(path);
    } else if (
      /\.(tsx?|css)$/.test(entry.name) &&
      !/\.test\.tsx?$/.test(entry.name) &&
      !SKIP_FILES.has(entry.name)
    ) {
      yield path;
    }
  }
}

const isMain =
  process.argv[1] !== undefined && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isMain) {
  const src = fileURLToPath(new URL("../src", import.meta.url));
  let count = 0;
  for (const file of walk(src)) {
    for (const v of findViolations(readFileSync(file, "utf8"))) {
      count += 1;
      console.error(`${relative(src, file)}:${v.line}: color literal — use a token: ${v.text}`);
    }
  }
  console.log(`color guard: ${count} violation(s)`);
  process.exit(count > 0 ? 1 : 0);
}
