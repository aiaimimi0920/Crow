import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { loadUserscriptParts } from "../build-userscript.mjs";

const source = "(function() {\n" + loadUserscriptParts()[0].body;
const token = "fixture_worker_token_".repeat(3);
const key = "uni_collection_credential";

function runtime({ search = "", credential, operatorCredential, version = "5.5.0", port = "8001", prompt = null } = {}) {
  const values = new Map([["uni_api_port", port]]);
  if (credential !== undefined) values.set(key, credential);
  if (operatorCredential !== undefined) values.set("uni_operator_credential", operatorCredential);
  const requests = [], logs = [], menus = [], timers = new Map();
  let timerId = 0, aborted = 0;
  const context = vm.createContext({
    URL, URLSearchParams,
    window: { location: { search }, prompt: () => prompt, addEventListener() {} },
    sessionStorage: { getItem: () => null, setItem() {} },
    GM_info: { version, scriptHandler: "Tampermonkey" },
    GM_getValue: (name, fallback) => values.has(name) ? values.get(name) : fallback,
    GM_setValue: (name, value) => values.set(name, value),
    GM_registerMenuCommand: (_name, callback) => menus.push(callback),
    GM_xmlhttpRequest: (request) => {
      requests.push(request);
      return { abort() { aborted++; request.onabort(); } };
    },
    log: (message) => logs.push(message),
    setTimeout: (callback) => { timers.set(++timerId, callback); return timerId; },
    clearTimeout: (id) => timers.delete(id),
  });
  vm.runInContext(source + "\nglobalThis.callApi = fetchApi;\n})();", context);
  return { context, values, requests, logs, menus, timers, aborted: () => aborted };
}

function configured(options = {}) {
  return runtime({ credential: { origin: "http://127.0.0.1:8001", token }, ...options });
}

test("worker header is bound to configured loopback API and read again on rotation", () => {
  const run = configured();
  run.context.callApi("/collection/seeds/batch", { items: [] });
  const request = run.requests[0];
  assert.equal(request.url, "http://127.0.0.1:8001/api/collection/seeds/batch");
  assert.equal(request.headers["X-FAPAI-Collection-Token"], token);
  assert.equal(request.method, "POST");
  assert.equal(request.redirect, "error");
  assert.equal(request.anonymous, true);
  run.values.set(key, { origin: "http://127.0.0.1:8001", token: token + "rotated" });
  run.context.callApi("/status");
  assert.equal(run.requests[1].headers["X-FAPAI-Collection-Token"], token + "rotated");
});

test("URL-selected port cannot receive another port's configured credential", () => {
  const run = configured({ search: "?uni_port=9000" });
  let errors = 0;
  run.context.callApi("/save", { items: [] }, null, () => errors++);
  assert.equal(run.requests.length, 0);
  assert.equal(errors, 1);
  assert.ok(!run.logs.join(" ").includes(token));
});

for (const endpoint of [null, 42, {}, "https://evil.test/api/save", "//evil.test", "/../save", "/%2e%2e/save", "/save#fragment", "/save\\outside", "/save\n", "/foo//bar"]) {
  test(`rejects ambiguous endpoint ${JSON.stringify(endpoint)}`, () => {
    const run = configured();
    run.context.callApi(endpoint);
    assert.equal(run.requests.length, 0);
  });
}

test("query data remains encoded and credential is absent until provisioned", () => {
  const run = runtime();
  run.context.callApi("/get_item?id=abc%2Fdef");
  assert.equal(run.requests[0].url, "http://127.0.0.1:8001/api/get_item?id=abc%2Fdef");
  assert.equal(run.requests[0].headers["X-FAPAI-Collection-Token"], undefined);
});

test("invalid credential or unsupported manager fails before network I/O", () => {
  for (const options of [{ version: "5.4.0" }, { version: "unknown" }, { credential: {} }, { credential: { origin: "http://127.0.0.1:8001", token: "bad" } }]) {
    const run = configured(options);
    run.context.callApi("/status");
    assert.equal(run.requests.length, 0);
  }
});

test("menu stores no token in page state and uses configured rather than URL-selected port", () => {
  const run = runtime({ search: "?uni_port=9000", prompt: token });
  run.menus[0]();
  assert.equal(run.values.get(key).origin, "http://127.0.0.1:8001");
  assert.equal(run.values.get(key).token, token);
  assert.ok(!JSON.stringify(run.context.window).includes(token));
  assert.ok(!run.logs.join(" ").includes(token));
  for (const prompt of [null, "bad"]) {
    const existing = configured({ prompt });
    existing.menus[0]();
    assert.equal(existing.values.get(key).token, token);
  }
});

test("timeout aborts once and late callbacks cannot report success", () => {
  const run = configured();
  let successes = 0, errors = 0;
  run.context.callApi("/status", {}, () => successes++, () => errors++);
  [...run.timers.values()][0]();
  run.requests[0].onload({ status: 200, responseText: "{}" });
  assert.equal(run.aborted(), 1);
  assert.equal(errors, 1);
  assert.equal(successes, 0);
  assert.equal(run.timers.size, 0);
});

test("failed, redirected, and invalid JSON responses have sanitized single failure", () => {
  for (const response of [{ status: 302 }, { status: 403, responseText: token }, { status: 200, responseText: "not json" }, { status: 200, finalUrl: "https://evil.test/", responseText: "{}" }]) {
    const run = configured();
    let errors = 0;
    run.context.callApi("/status", {}, () => assert.fail("unexpected success"), () => errors++);
    run.requests[0].onload(response);
    run.requests[0].onerror();
    assert.equal(errors, 1);
    assert.equal(run.timers.size, 0);
    assert.ok(!run.logs.join(" ").includes(token));
  }
});

test("successful response clears deadline and invokes callback once", () => {
  const run = configured();
  let calls = 0;
  run.context.callApi("/status", {}, (body) => { assert.equal(body.ok, true); calls++; });
  run.requests[0].onload({ status: 200, responseText: '{"ok":true}' });
  run.requests[0].onload({ status: 200, responseText: '{"ok":true}' });
  assert.equal(calls, 1);
  assert.equal(run.timers.size, 0);
});

test("empty task claims use POST and require a configured worker credential", () => {
  for (const path of ["/collection/details/tasks", "/collection/details/next_task", "/get_next_task"]) {
    const run = configured();
    run.context.callApi(path);
    assert.equal(run.requests[0].method, "POST");
    assert.equal(run.requests[0].data, "{}");
    assert.equal(run.requests[0].headers["X-FAPAI-Collection-Token"], token);
    const missing = runtime();
    missing.context.callApi(path);
    assert.equal(missing.requests.length, 0);
  }
});

test("operator actions use only the separately configured operator credential", () => {
  const operator = token + "operator";
  const run = configured({ operatorCredential: { origin: "http://127.0.0.1:8001", token: operator } });
  run.context.callApi("/collection/control/resume");
  run.context.callApi("/approve_area", { id: "fixture" });
  for (const request of run.requests) {
    assert.equal(request.method, "POST");
    assert.equal(request.headers["X-FAPAI-Control-Token"], operator);
    assert.equal(request.headers["X-FAPAI-Collection-Token"], undefined);
  }
  const missing = configured();
  missing.context.callApi("/collection/control/resume");
  assert.equal(missing.requests.length, 0);
  const reused = configured({ prompt: token });
  reused.menus[1]();
  assert.equal(reused.values.has("uni_operator_credential"), false);
});
