import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { loadUserscriptParts } from "../build-userscript.mjs";

const parts = loadUserscriptParts();

function sessions(stored = null, cryptoAvailable = true) {
  const values = new Map([["sniff_sessions_list", stored]]);
  let entropyCalls = 0;
  const math = Object.create(Math);
  math.random = () => assert.fail("lease ownership IDs must not use Math.random");
  const context = {
    URL, URLSearchParams, Math: math, log() {},
    window: { location: { search: "" }, addEventListener() {} },
    GM_getValue: (_name, fallback) => fallback, GM_registerMenuCommand() {},
    sessionStorage: {
      getItem: (name) => values.get(name) ?? null,
      setItem: (name, value) => values.set(name, value),
    },
  };
  if (cryptoAvailable) context.crypto = { getRandomValues(bytes) {
    assert.equal(bytes.length, 16);
    bytes.fill(++entropyCalls);
    return bytes;
  } };
  const run = () => vm.runInNewContext("(function() {\n" + parts[0].body +
    "\nreturn sniffSessions;\n})();", context);
  return { values, run, entropyCalls: () => entropyCalls };
}

test("new lease ownership sessions use 128 cryptographic random bits each", () => {
  const fixture = sessions();
  const result = Array.from(fixture.run());
  assert.equal(fixture.entropyCalls(), 3);
  assert.equal(new Set(result).size, 3);
  for (let index = 0; index < 3; index++) {
    assert.match(result[index], new RegExp(`^sniff_s${index}_\\d+_${String(index + 1).padStart(2, "0").repeat(16)}$`));
  }
  assert.deepEqual(JSON.parse(fixture.values.get("sniff_sessions_list")), result);
});

test("existing sessions retain active lease ownership on reload", () => {
  const existing = ["sniff_s0_legacy", "sniff_s1_legacy", "sniff_s2_legacy"];
  const fixture = sessions(JSON.stringify(existing), false);
  assert.deepEqual(Array.from(fixture.run()), existing);
  assert.equal(fixture.entropyCalls(), 0);
});

test("no weak fallback is persisted when browser entropy is unavailable", () => {
  const fixture = sessions(null, false);
  assert.throws(fixture.run, /crypto is not defined/);
  assert.equal(fixture.values.get("sniff_sessions_list"), null);
});

function standby(task) {
  const rows = [], intervals = [], timeouts = [], deleted = [];
  const log = {
    scrollHeight: 450, scrollTop: 0,
    appendChild: (node) => rows.push(node),
    set innerHTML(_value) { assert.fail("log must never parse HTML"); },
  };
  const window = { name: "fixture", location: new URL("https://sf.taobao.com/?__captcha_worker_master=1") };
  const document = {
    body: { innerHTML: "" },
    getElementById: (id) => id === "cw-log" ? log : { style: {} },
    createElement: (tag) => ({ tag, textContent: "" }),
  };
  vm.runInNewContext("(function() {\n" + parts[10].body + "\n})();", {
    window, document, console: { log() {} },
    GM_getValue: () => task, GM_deleteValue: (name) => deleted.push(name),
    setInterval: (callback) => intervals.push(callback),
    setTimeout: (callback) => timeouts.push(callback),
  });
  return { rows, log, window, intervals, timeouts, deleted };
}

test("worker task text becomes a literal log row, preserving rows and scroll", () => {
  const url = 'https://sf-item.taobao.com/item.htm?id=1&note=<img src=x onerror="alert(1)">';
  const fixture = standby({ url, timestamp: Date.now() });
  const first = fixture.rows[0];
  fixture.intervals[0]();
  assert.equal(fixture.rows.length, 2);
  assert.equal(fixture.rows[0], first);
  assert.equal(fixture.rows[1].tag, "div");
  assert.ok(fixture.rows[1].textContent.endsWith(`收到跳转任务: ${url}`));
  assert.equal(fixture.log.scrollTop, fixture.log.scrollHeight);
  assert.ok(fixture.deleted.includes("uni_captcha_queue"));
  assert.equal(fixture.timeouts.length, 1);
  // Navigation is deliberately not executed by this offline DOM-safety test.
});

test("stale worker tasks remain visible as text and are not navigated", () => {
  const fixture = standby({ url: "https://sf-item.taobao.com/item.htm?id=1", timestamp: 0 });
  fixture.intervals[0]();
  assert.match(fixture.rows[1].textContent, /丢弃过期任务/);
  assert.equal(fixture.timeouts.length, 0);
  assert.ok(fixture.deleted.includes("uni_captcha_queue"));
});
