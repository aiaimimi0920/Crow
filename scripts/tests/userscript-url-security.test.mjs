import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const pageSource = fs.readFileSync(new URL("../../tampermonkey_scripts/src/fapaifang_unified/20_sniff_challenge.js", import.meta.url), "utf8");
const flagsSource = pageSource.slice(pageSource.indexOf("// Page Type Detection"), pageSource.indexOf("const urlParams"));
const ncSource = fs.readFileSync(new URL("../../userscripts/nc_captcha_solver.user.js", import.meta.url), "utf8");

test("unified userscript classifies only the exact supported hosts", () => {
  for (const [hostname, expected] of [
    ["sf.taobao.com", [true, false, false]],
    ["sf-item.taobao.com", [false, true, false]],
    ["susong-item.taobao.com", [false, true, false]],
    ["paimai.taobao.com", [false, true, false]],
    ["login.taobao.com", [false, false, true]],
    ["sec.taobao.com", [false, false, true]],
    ["sf-item.taobao.com.attacker.test", [false, false, false]],
    ["paimai.taobao.com.attacker.test", [false, false, false]],
    ["evil-login.taobao.com", [false, false, false]],
    ["sec.taobao.com.attacker.test", [false, false, false]],
  ]) {
    const context = { window: { location: { hostname } } };
    vm.runInNewContext(flagsSource + "globalThis.flags = [isMaster, isDetail, isLoginOrSec];", context);
    assert.deepEqual(Array.from(context.flags), expected, hostname);
  }
});

function ncRuntime() {
  let receive, solved = 0;
  const messages = [];
  const window = {
    location: { origin: "https://sf.taobao.com" },
    addEventListener: (name, handler) => { if (name === "message") receive = handler; },
    NoCaptcha: { _captchaIns: { success: () => solved++ } },
    postMessage: (data, origin) => messages.push({ data, origin }),
  };
  const document = { querySelector: () => ({ className: "nc-success" }) };
  const source = ncSource.replace(/\}\)\(\);\s*$/, "window.checkSuccessForTest = checkSuccess;\n})();");
  vm.runInNewContext(source, { window, document, setTimeout() {}, console: { log() {} } });
  return { window, messages, receive: (event) => receive(event), solved: () => solved };
}

test("NC message commands require both this window and its exact origin", () => {
  const run = ncRuntime();
  for (const event of [
    { origin: "https://attacker.test", source: run.window },
    { origin: "https://sf.taobao.com.attacker.test", source: run.window },
    { origin: "null", source: run.window },
    { origin: "https://sf.taobao.com", source: {} },
    { origin: "https://sf.taobao.com", source: null },
  ]) run.receive({ ...event, data: { type: "SOLVE_NC_CAPTCHA" } });
  assert.equal(run.solved(), 0);
  run.receive({ origin: run.window.location.origin, source: run.window, data: { type: "other" } });
  assert.equal(run.solved(), 0);
  run.receive({ origin: run.window.location.origin, source: run.window, data: { type: "SOLVE_NC_CAPTCHA" } });
  assert.equal(run.solved(), 1);
  run.window.solveNCCaptcha();
  assert.equal(run.solved(), 2);
});

test("NC result messages use the current origin rather than a wildcard", () => {
  const run = ncRuntime();
  run.window.checkSuccessForTest();
  assert.equal(run.messages.length, 1);
  assert.equal(run.messages[0].origin, run.window.location.origin);
  assert.equal(run.messages[0].data.type, "NC_SOLVED");
});
