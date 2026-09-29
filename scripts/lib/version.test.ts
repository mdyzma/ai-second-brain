import assert from "node:assert/strict";
import { test } from "node:test";
import { assertSemver, setPackageJsonVersion, setPyprojectVersion } from "./version.ts";

const PYPROJECT = [
  "[project]",
  'name = "ai-second-brain"',
  'version = "0.2.0"',
  "",
  "[tool.other]",
  'version = "9.9.9"',
  "",
].join("\n");

test("setPyprojectVersion replaces only the [project] version", () => {
  const updated = setPyprojectVersion(PYPROJECT, "1.2.3");
  assert.match(updated, /\[project\]\nname = "ai-second-brain"\nversion = "1\.2\.3"\n/);
  assert.match(updated, /\[tool\.other\]\nversion = "9\.9\.9"/);
});

test("setPyprojectVersion throws when [project] has no version", () => {
  assert.throws(() => setPyprojectVersion('[project]\nname = "x"\n', "1.0.0"), /no \[project\] version/);
});

test("setPackageJsonVersion adds the version right after the name", () => {
  const updated = setPackageJsonVersion('{"name":"@x/web","private":true}', "0.2.0");
  assert.equal(updated, '{\n  "name": "@x/web",\n  "version": "0.2.0",\n  "private": true\n}\n');
});

test("setPackageJsonVersion replaces an existing version", () => {
  const updated = setPackageJsonVersion('{"name":"w","version":"0.1.0","type":"module"}', "0.3.0");
  assert.deepEqual(JSON.parse(updated), { name: "w", version: "0.3.0", type: "module" });
});

for (const bad of ["v1.2.3", "1.2", "latest", "", "1.2.3; rm -rf /"]) {
  test(`assertSemver rejects ${JSON.stringify(bad)}`, () => {
    assert.throws(() => assertSemver(bad), /Not a SemVer version/);
  });
}

test("assertSemver accepts release and pre-release versions", () => {
  assertSemver("0.2.0");
  assertSemver("1.0.0-rc.1");
});
