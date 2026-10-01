import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import vm from "node:vm";
import { pathToFileURL } from "node:url";

const generator = new URL("../../game/web-app/scripts/build-entry.mjs", import.meta.url);
function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "crow-game-entry-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, "scripts"));
  const script = path.join(root, "scripts/build-entry.mjs");
  fs.copyFileSync(generator, script);
  return { root, script, entry: path.join(root, "index.html") };
}
function run(script) {
  const result = spawnSync(process.execPath, [script], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
}

test("a clean game checkout receives the existing Vue and local CSS entrypoints", (t) => {
  const { script, entry } = fixture(t);
  run(script);
  const content = fs.readFileSync(entry, "utf8");
  assert.match(content, /id="app"/);
  assert.match(content, /type="module" src="\/src\/main\.js"/);
  assert.match(content, /href="\/runtime-tailwind\.css"/);
  assert.doesNotMatch(content, /https?:\/\//);
  run(script);
  assert.equal(fs.readFileSync(entry, "utf8"), content);
});

test("existing locally customized entrypoints are never overwritten", (t) => {
  const { script, entry } = fixture(t);
  fs.writeFileSync(entry, "<!doctype html><!-- preserved local entry -->");
  run(script);
  assert.equal(fs.readFileSync(entry, "utf8"), "<!doctype html><!-- preserved local entry -->");
});

test("exclusive creation preserves a file appearing at the write boundary", (t) => {
  const { script, entry } = fixture(t);
  const source = fs.readFileSync(script, "utf8")
    .replace("import fs from 'node:fs'", "")
    .replace("import.meta.url", "fixtureScriptUrl");
  const fakeFs = { writeFileSync(target, content, options) {
    fs.writeFileSync(entry, "new concurrent custom entry");
    assert.equal(options.flag, "wx");
    return fs.writeFileSync(target, content, options);
  } };
  vm.runInNewContext(source, { fs: fakeFs, URL, fixtureScriptUrl: pathToFileURL(script).href });
  assert.equal(fs.readFileSync(entry, "utf8"), "new concurrent custom entry");
});

test("entry creation does not swallow failures other than already existing", (t) => {
  const { script } = fixture(t);
  const source = fs.readFileSync(script, "utf8")
    .replace("import fs from 'node:fs'", "")
    .replace("import.meta.url", "fixtureScriptUrl");
  const failure = Object.assign(new Error("write denied"), { code: "EACCES" });
  assert.throws(() => vm.runInNewContext(source, {
    fs: { writeFileSync() { throw failure; } }, URL,
    fixtureScriptUrl: pathToFileURL(script).href,
  }), /write denied/);
});

test("both build and dev generate their local stylesheet before Vite starts", () => {
  const app = JSON.parse(fs.readFileSync(new URL("../../game/web-app/package.json", import.meta.url)));
  for (const mode of ["build", "dev"]) {
    assert.equal(app.scripts[`pre${mode}`], "node scripts/build-entry.mjs");
    assert.match(app.scripts[mode], /^npm run build:runtime-css && vite(?: build)?$/);
  }
});
