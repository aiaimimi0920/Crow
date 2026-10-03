import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const normalizeLineEndings = (text) => text.replace(/\r\n/g, "\n");
const read = (name) => normalizeLineEndings(fs.readFileSync(path.join(root, name), "utf8"));
const workflows = fs.readdirSync(path.join(root, ".github/workflows"))
  .filter((name) => /\.ya?ml$/.test(name))
  .map((name) => [name, read(`.github/workflows/${name}`)]);
const lockfiles = [
  "requirements.lock", "requirements-dev.lock", "collector-desktop/package-lock.json",
  "collector-desktop/src-tauri/Cargo.lock", "game/web-app/package-lock.json",
];

test("policy input normalization preserves content for LF and CRLF checkouts", () => {
  const policy = "permissions:\n  contents: read\nfail-on-vuln: true\n";
  assert.equal(normalizeLineEndings(policy), policy);
  assert.equal(normalizeLineEndings(policy.replace(/\n/g, "\r\n")), policy);
  const unsafe = "fail-on-vuln: false\r\ncontinue-on-error: true\r\n";
  assert.doesNotMatch(normalizeLineEndings(unsafe), /fail-on-vuln: true/);
  assert.match(normalizeLineEndings(unsafe), /continue-on-error:\s*true/);
});

test("workflow actions are immutable and checks do not run privileged PR code", () => {
  for (const [name, text] of workflows) {
    assert.doesNotMatch(text, /pull_request_target\s*:/, name);
    assert.doesNotMatch(text, /continue-on-error:\s*true/, name);
    assert.doesNotMatch(text, /secrets:\s*inherit/, name);
    assert.match(text, /permissions:\n  contents: read/, name);
    for (const [, target] of text.matchAll(/\buses:\s*([^\s#]+)/g)) {
      if (!target.startsWith("./")) assert.match(target, /^[\w./-]+@[a-f0-9]{40}$/, name);
    }
    const checkouts = text.split(/uses: actions\/checkout@/).slice(1);
    for (const checkout of checkouts) {
      assert.match(checkout.split(/\n      - /)[0], /persist-credentials: false/, name);
    }
  }
});

test("OSV explicitly scans all production and development lockfiles and fails closed", () => {
  const text = read(".github/workflows/dependency-security.yml");
  const scanned = [...text.matchAll(/--lockfile=(?:requirements\.txt:)?\.\/([^\s]+)/g)]
    .map((match) => match[1]).sort();
  assert.deepEqual(scanned, [...lockfiles].sort());
  for (const file of lockfiles) assert.ok(fs.statSync(path.join(root, file)).isFile(), file);
  assert.match(text, /fail-on-vuln: true/);
  assert.match(text, /upload-sarif: true/);
  assert.doesNotMatch(text, /--config|--ignore|--experimental/);
  assert.equal((text.match(/--lockfile=requirements\.txt:/g) || []).length, 2);
});

test("game watcher override removes the vulnerable braces dependency chain", () => {
  const manifest = JSON.parse(read("game/web-app/package.json"));
  const { packages } = JSON.parse(read("game/web-app/package-lock.json"));
  const version = manifest.overrides["@tailwindcss/cli"]["@parcel/watcher"];
  assert.equal(packages["node_modules/@parcel/watcher"].version, version);
  for (const [name, dependency] of Object.entries(packages)) {
    assert.doesNotMatch(name, /\/node_modules\/(?:braces|micromatch)$/);
    assert.doesNotMatch(name, /^node_modules\/(?:braces|micromatch)$/);
    if (name.startsWith("node_modules/@parcel/watcher-")) {
      assert.equal(dependency.version, version, name);
    }
  }
});

test("CodeQL covers every code ecosystem with explicit no-build analysis", () => {
  const text = read(".github/workflows/codeql.yml");
  assert.match(text, /language: \[python, javascript-typescript, rust, actions\]/);
  assert.match(text, /build-mode: none/);
  assert.match(text, /queries: security-extended/);
  assert.match(text, /    env:\n(?:      #[^\n]*\n)*      CODEQL_ACTION_DIFF_INFORMED_QUERIES: 'false'/);
  assert.match(text, /security-events: write/);
  assert.match(text, /branches: \[master\]/);
  assert.match(text, /output: codeql-results/);
  assert.match(text, /run: python3 scripts\/summarize_codeql_results\.py codeql-results/);
  assert.doesNotMatch(text, /upload:\s*never|skip-queries:\s*true/);
});

test("Dependabot covers both npm apps, Rust, Python and CI actions", () => {
  const text = read(".github/dependabot.yml");
  for (const ecosystem of ["github-actions", "pip", "npm", "cargo"])
    assert.match(text, new RegExp(`package-ecosystem: ${ecosystem}\\n`));
  for (const directory of ["/collector-desktop", "/game/web-app", "/collector-desktop/src-tauri"])
    assert.ok(text.includes(directory), directory);
  assert.doesNotMatch(text, /ignore:\s*\n/);
});

test("secret scanning verifies its binary and never prints raw findings", () => {
  const text = read("scripts/scan-secrets.sh");
  assert.match(text, /sha256=[a-f0-9]{64}/);
  assert.match(text, /sha256sum --check --status/);
  assert.match(text, /--redact=100/);
  assert.match(text, /--exit-code=1/);
  assert.match(text, /git -C "\$root" ls-files -z/);
  assert.doesNotMatch(text, /--exit-code=0|\|\| true/);
});

test("reviewed secret false positives remain exact values scoped to one detector", () => {
  const text = read(".gitleaks.toml");
  assert.match(text, /useDefault = true/);
  assert.match(text, /targetRules = \["generic-api-key"\]/);
  assert.match(text, /regexTarget = "secret"/);
  const expressions = [...text.matchAll(/'''\^([^\n]+)\$'''/g)];
  assert.equal(expressions.length, 7);
  assert.doesNotMatch(text, /paths\s*=|stopwords\s*=|\.\*/);
  assert.match(read("scripts/scan-secrets.sh"), /test-secret-scan\.sh/);
});
