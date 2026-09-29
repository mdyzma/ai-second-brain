import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parse, wcagContrast } from "culori";

export type Failure = { theme: string; fg: string; bg: string; ratio: number; min: number };
type Vars = Map<string, string>;

const TEXT = 4.5;
const NON_TEXT = 3;
const BASE_PAIRS: Array<[string, string, number]> = [
  ["--sb-text", "--sb-bg", TEXT],
  ["--sb-text", "--sb-surface", TEXT],
  ["--sb-text", "--sb-surface-raised", TEXT],
  ["--sb-text-muted", "--sb-bg", TEXT],
  ["--sb-text-muted", "--sb-surface", TEXT],
  ["--sb-text-muted", "--sb-surface-raised", TEXT],
  ["--sb-accent-fg", "--sb-accent", TEXT],
  ["--sb-border-input", "--sb-bg", NON_TEXT],
  ["--sb-border-input", "--sb-surface", NON_TEXT],
  ["--sb-focus-ring", "--sb-bg", NON_TEXT],
  ["--sb-focus-ring", "--sb-surface", NON_TEXT],
];

function collect(css: string, selector: RegExp): Vars {
  const vars: Vars = new Map();
  for (const block of css.matchAll(selector)) {
    for (const match of (block[1] ?? "").matchAll(/(--sb-[\w-]+)\s*:\s*([^;]+);/g)) {
      const [, name, value] = match;
      if (name && value) vars.set(name, value.trim());
    }
  }
  return vars;
}

function resolveVar(name: string, vars: Vars, depth = 0): string | undefined {
  const value = vars.get(name);
  if (value === undefined || depth > 10) return undefined;
  const alias = /^var\((--sb-[\w-]+)\)$/.exec(value);
  return alias?.[1] ? resolveVar(alias[1], vars, depth + 1) : value;
}

function pairsFor(vars: Vars): Array<[string, string, number]> {
  const pairs = [...BASE_PAIRS];
  for (const name of vars.keys()) {
    if (name.endsWith("-fg") && name !== "--sb-accent-fg") {
      const prefix = name.slice(0, -3);
      if (vars.has(`${prefix}-bg`)) pairs.push([name, `${prefix}-bg`, TEXT]);
      pairs.push([name, "--sb-bg", TEXT], [name, "--sb-surface", TEXT]);
    }
    if (name.endsWith("-border") && name !== "--sb-border" && name !== "--sb-border-input") {
      pairs.push([name, "--sb-bg", NON_TEXT]);
    }
  }
  return pairs;
}

export function checkTokens(css: string): { failures: Failure[]; checked: number } {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const light = collect(clean, /:root\s*\{([^}]*)\}/g);
  const dark = new Map([...light, ...collect(clean, /\[data-theme="dark"\]\s*\{([^}]*)\}/g)]);
  const failures: Failure[] = [];
  let checked = 0;
  for (const [theme, vars] of [
    ["light", light],
    ["dark", dark],
  ] as const) {
    for (const [fg, bg, min] of pairsFor(vars)) {
      if (!vars.has(fg) || !vars.has(bg)) {
        if (BASE_PAIRS.some(([f, b]) => f === fg && b === bg)) {
          failures.push({ theme, fg, bg, ratio: 0, min });
        }
        continue;
      }
      checked += 1;
      const fgColor = parse(resolveVar(fg, vars) ?? "");
      const bgColor = parse(resolveVar(bg, vars) ?? "");
      const ratio = fgColor && bgColor ? wcagContrast(fgColor, bgColor) : 0;
      if (ratio < min) failures.push({ theme, fg, bg, ratio: Math.round(ratio * 100) / 100, min });
    }
  }
  return { failures, checked };
}

const isMain =
  process.argv[1] !== undefined && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isMain) {
  const tokensPath = fileURLToPath(new URL("../src/design-system/tokens.css", import.meta.url));
  const { failures, checked } = checkTokens(readFileSync(tokensPath, "utf8"));
  for (const f of failures) {
    console.error(`[${f.theme}] ${f.fg} on ${f.bg}: ${f.ratio}:1 (needs ${f.min}:1)`);
  }
  console.log(`contrast: ${checked} pairs checked, ${failures.length} failing`);
  process.exit(failures.length > 0 ? 1 : 0);
}
