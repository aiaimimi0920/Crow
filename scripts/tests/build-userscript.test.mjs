import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  OUTPUT_PATH,
  PART_PATHS,
  buildUserscriptSource,
  checkUserscriptOutput,
} from "../build-userscript.mjs";


const REVIEWED_SOURCE_SHA256 =
  "8867e0daf09ef83930d5b492dad6321c718cf55c792ddbb703d1019f4039b4b2";


test("userscript parts deterministically reproduce the installable script", () => {
  assert.equal(new Set(PART_PATHS).size, PART_PATHS.length);
  for (const partPath of PART_PATHS) {
    assert.equal(path.extname(partPath), ".js");
    assert.ok(fs.statSync(partPath).isFile());
  }
  checkUserscriptOutput();
});


test("userscript build keeps metadata first and one shared IIFE", () => {
  const source = buildUserscriptSource();
  assert.ok(source.startsWith("// ==UserScript==\n"));
  assert.ok(source.includes("// ==/UserScript==\n"));
  assert.equal((source.match(/\(function\(\) \{/g) || []).length, 1);
  assert.ok(source.trimEnd().endsWith("})();"));
  assert.ok(fs.readFileSync(OUTPUT_PATH, "utf8").length > 0);
});


test("generated script matches the reviewed authenticated client revision", () => {
  const digest = crypto
    .createHash("sha256")
    .update(buildUserscriptSource(), "utf8")
    .digest("hex");
  assert.equal(digest, REVIEWED_SOURCE_SHA256);
});
