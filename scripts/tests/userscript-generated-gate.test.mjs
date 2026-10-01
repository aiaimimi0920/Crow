import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import {
  buildUserscriptSource,
  checkUserscriptOutput,
  OUTPUT_RELATIVE_PATH,
  PART_RELATIVE_PATHS,
} from "../build-userscript.mjs";
import {
  evaluateRows,
  scanRepository,
  verifyGeneratedArtifacts,
} from "../effective-code-lines.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const policy = JSON.parse(fs.readFileSync(path.join(repoRoot, "scripts/effective-code-lines-policy.json"), "utf8"));

function fixture({ missing, suffix = "", stale = false } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "crow-generated-gate-"));
  for (const relative of [...PART_RELATIVE_PATHS, OUTPUT_RELATIVE_PATH]) {
    if (relative === missing) continue;
    const destination = path.join(root, relative);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.copyFileSync(path.join(repoRoot, relative), destination);
  }
  if (suffix) {
    const lastPart = path.join(root, PART_RELATIVE_PATHS.at(-1));
    const source = fs.readFileSync(lastPart, "utf8");
    fs.writeFileSync(lastPart, source.slice(0, -2) + suffix + "}\n", "utf8");
    if (!stale) fs.writeFileSync(path.join(root, OUTPUT_RELATIVE_PATH), buildUserscriptSource(root), "utf8");
  }
  return root;
}

function verify(root, config = policy) {
  const { rows, diagnostics } = scanRepository(root, config);
  assert.deepEqual(diagnostics, []);
  return verifyGeneratedArtifacts(root, config, rows);
}

test("only the generated install file receives the reviewed exception", () => {
  const root = fixture();
  const generated = verify(root);
  assert.deepEqual(generated.map((row) => row.path), [OUTPUT_RELATIVE_PATH]);
  assert.ok(generated[0].effectiveLines > 1500);
  assert.equal(scanRepository(root, policy).rows.length, PART_RELATIVE_PATHS.length + 1);
});

for (const missing of [OUTPUT_RELATIVE_PATH, PART_RELATIVE_PATHS[0]]) {
  test(`missing required file fails: ${missing}`, () => {
    const root = fixture({ missing });
    assert.throws(() => verify(root), /must remain scanned/);
    assert.throws(() => checkUserscriptOutput(root), /ENOENT/);
  });
}

test("stale output and hand-edited output both fail", () => {
  const staleRoot = fixture({ suffix: "\nvoid 0;\n", stale: true });
  assert.throws(() => verify(staleRoot), /output is stale/);
  const editedRoot = fixture();
  fs.appendFileSync(path.join(editedRoot, OUTPUT_RELATIVE_PATH), "\nvoid 1;\n", "utf8");
  assert.throws(() => verify(editedRoot), /output is stale/);
});

test("matching generation cannot exempt syntactically invalid JavaScript", () => {
  const root = fixture({ suffix: "\nconst = ;\n" });
  assert.throws(() => verify(root), /syntax check failed/);
});

test("source-unit wrappers cannot silently discard executable preambles or suffixes", () => {
  for (const side of ["before", "after"]) {
    const root = fixture();
    const part = path.join(root, PART_RELATIVE_PATHS[1]);
    const source = fs.readFileSync(part, "utf8");
    fs.writeFileSync(part, side === "before" ? "void 0;\n" + source : source + "void 0;\n");
    assert.throws(() => buildUserscriptSource(root), /source unit/);
  }
});

test("excluding a maintained fragment fails even with a matching install file", () => {
  const root = fixture();
  const config = structuredClone(policy);
  config.excludedPaths.push({ path: PART_RELATIVE_PATHS[0], reason: "Invalid exclusion fixture." });
  assert.throws(() => verify(root, config), /must remain scanned/);
});

test("oversized fragments and sibling scripts still fail the handwritten gate", () => {
  const root = fixture({ suffix: "\nvoid 0;\n".repeat(701) });
  fs.writeFileSync(path.join(root, "tampermonkey_scripts", "other.user.js"), "void 0;\n".repeat(1501), "utf8");
  const generated = verify(root);
  const rows = scanRepository(root, policy).rows.filter((row) => !generated.some((item) => item.path === row.path));
  const result = evaluateRows(rows, { files: [] }, new Map(), "ratchet");
  assert.equal(result.violations.length, 2);
  assert.ok(result.violations.some((message) => message.startsWith(PART_RELATIVE_PATHS.at(-1))));
  assert.ok(result.violations.some((message) => message.startsWith("tampermonkey_scripts/other.user.js")));
});

test("policy cannot extend the exception to another output", () => {
  const root = fixture();
  const config = structuredClone(policy);
  config.generatedArtifacts[0].path = "tampermonkey_scripts/other.user.js";
  assert.throws(() => verify(root, config), /unapproved generated artifact/);
});
