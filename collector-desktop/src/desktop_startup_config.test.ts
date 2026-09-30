import assert from "node:assert/strict";
import test from "node:test";
import { startupApiBase } from "./desktop_startup_config.ts";
import { fetchWithTimeout, setConfigurationBlocked } from "./desktop_http.ts";

test("configuration conflict cannot silently fall back or issue network requests", async () => {
  const previous = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = async () => { requests += 1; return new Response("ok"); };
  try {
    for (const error of ["crow_configuration_alias_conflict:CROW_COLLECTOR_API_BASE,FAPAI_COLLECTOR_API_BASE", new Error("crow_configuration_alias_conflict:CROW_COLLECTOR_API_BASE,FAPAI_COLLECTOR_API_BASE")]) {
      const result = await startupApiBase(async () => { throw error; }, () => { throw new Error("unexpected fallback"); });
      assert.deepEqual(result, { apiBase: "", blocked: true });
      setConfigurationBlocked(result.blocked);
      await assert.rejects(fetchWithTimeout("http://127.0.0.1/api"), /configuration conflict/);
    }
    assert.equal(requests, 0);
    setConfigurationBlocked(false);
    await fetchWithTimeout("http://127.0.0.1/api");
    assert.equal(requests, 1);
  } finally { globalThis.fetch = previous; setConfigurationBlocked(false); }
});

test("native successful strings and non-Tauri browser fallback remain compatible", async () => {
  assert.deepEqual(await startupApiBase(async () => "https://fixture.invalid/api", () => "fallback"), { apiBase: "https://fixture.invalid/api", blocked: false });
  assert.deepEqual(await startupApiBase(async () => { throw new Error("not running inside Tauri"); }, () => "https://browser.invalid"), { apiBase: "https://browser.invalid", blocked: false });
});
