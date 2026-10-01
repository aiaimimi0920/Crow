import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";


const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SOURCE_ROOT = path.join(
  REPO_ROOT,
  "tampermonkey_scripts",
  "src",
  "fapaifang_unified",
);
export const OUTPUT_PATH = path.join(
  REPO_ROOT,
  "tampermonkey_scripts",
  "fapaifang_unified.user.js",
);
export const PART_PATHS = [
  "00_bootstrap.js",
  "10_sniff_collection.js",
  "20_sniff_challenge.js",
  "30_sniff_dashboard.js",
  "40_fast_review_loop.js",
  "50_fast_review_item.js",
  "60_slow_review.js",
  "70_detail_worker.js",
  "80_detail_helper_context.js",
  "90_detail_helper_panel.js",
  "100_detail_helper_actions.js",
  "110_dispatch_and_captcha.js",
].map((name) => path.join(SOURCE_ROOT, name));

export const OUTPUT_RELATIVE_PATH = path.relative(REPO_ROOT, OUTPUT_PATH).replaceAll("\\", "/");
export const PART_RELATIVE_PATHS = PART_PATHS.map((part) =>
  path.relative(REPO_ROOT, part).replaceAll("\\", "/"),
);


function normalizeLineEndings(content) {
  return content.replace(/\r\n?/g, "\n");
}


export function loadUserscriptParts(root = REPO_ROOT) {
  return PART_RELATIVE_PATHS.map((partPath, index) => {
    const source = normalizeLineEndings(fs.readFileSync(path.join(root, partPath), "utf8"));
    const name = path.basename(partPath, ".js");
    const opening = `function crowSource_${name}() {\n`;
    const start = source.indexOf(opening);
    assert.ok(start >= 0 && source.endsWith("\n}\n"), `Invalid source unit: ${partPath}`);
    const metadata = source.slice(0, start);
    assert.ok(index === 0 ? metadata.startsWith("// ==UserScript==\n") &&
      metadata.trimEnd().endsWith("// ==/UserScript==") &&
      metadata.split("\n").every((line) => !line.trim() || line.startsWith("//")) :
      metadata === "", `Unexpected code outside source unit: ${partPath}`);
    return { source, metadata, body: source.slice(start + opening.length, -2) };
  });
}


export function buildUserscriptSource(root = REPO_ROOT) {
  // Source units are valid JavaScript function bodies, not executed modules.
  // Splicing their complete bodies into one IIFE preserves shared bindings and
  // early returns. Both these units and the installable program remain scanned.
  const parts = loadUserscriptParts(root);
  return parts[0].metadata + "(function() {\n" +
    parts.map((part) => part.body).join("") + "})();\n";
}


export function checkUserscriptOutput(root = REPO_ROOT) {
  const expected = buildUserscriptSource(root);
  const actual = normalizeLineEndings(fs.readFileSync(path.join(root, OUTPUT_RELATIVE_PATH), "utf8"));
  assert.equal(
    actual,
    expected,
    "Tampermonkey output is stale; run node scripts/build-userscript.mjs --write",
  );
  for (const source of [...loadUserscriptParts(root).map((part) => part.source), actual]) {
    const syntax = spawnSync(process.execPath, ["--check", "--input-type=commonjs"], {
      input: source,
      encoding: "utf8",
      windowsHide: true,
      timeout: 30_000,
    });
    assert.equal(syntax.status, 0, `Tampermonkey syntax check failed: ${syntax.error?.message || syntax.stderr}`);
  }
}


export function writeUserscriptOutput() {
  const output = buildUserscriptSource().replace(/\n/g, "\r\n");
  fs.writeFileSync(OUTPUT_PATH, output, "utf8");
}


const invokedDirectly =
  process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedDirectly) {
  const mode = process.argv[2] || "--check";
  if (mode === "--check") checkUserscriptOutput();
  else if (mode === "--write") writeUserscriptOutput();
  else throw new Error(`Unknown mode: ${mode}`);
}
