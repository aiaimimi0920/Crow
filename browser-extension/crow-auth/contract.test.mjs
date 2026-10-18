import test from "node:test";
import assert from "node:assert/strict";
import { targetIdentity, selectCookies, nativeFailure } from "./contract.mjs";

test("native startup errors remain distinct without exposing arbitrary messages", () => {
  assert.equal(nativeFailure("Specified native messaging host not found."), "native_not_found");
  assert.equal(nativeFailure("Native host has exited."), "native_exited");
  assert.equal(nativeFailure("Failed to start native messaging host."), "native_start_failed");
  assert.equal(nativeFailure("Access to the specified native messaging host is forbidden."), "native_forbidden");
  assert.equal(nativeFailure("Error when communicating with the native messaging host."), "native_protocol_failed");
  assert.equal(nativeFailure("secret-cookie"), "native_unavailable");
  assert.equal(nativeFailure("toString"), "native_unavailable");
});

test("only real targets; ignore only our transient parameter", () => {
  const url = "https://sf.taobao.com/list/a.htm";
  assert.equal(targetIdentity(`${url}?b=2&a=1&__captcha_solver_bg=1#fragment`), `${url}?a=1&b=2`);
  for (const bad of ["http://sf.taobao.com/list/a", "https://evil.invalid/list/a", "https://sf.taobao.com/login",
    "https://user@sf.taobao.com/list/a", "https://sf-item.taobao.com/sf_item/no.htm"]) {
    assert.throws(() => targetIdentity(bad));
  }
});

test("scoped cookies deduplicated; partition data never silently lost", () => {
  const cookie = { name: "x", domain: ".taobao.com", path: "/" };
  assert.deepEqual(selectCookies([[cookie], [cookie, { ...cookie, domain: ".evil.invalid" }]]), [cookie]);
  assert.throws(() => selectCookies([[{ ...cookie, partitionKey: { topLevelSite: "https://taobao.com" } }]]));
  assert.throws(() => selectCookies([[]]));
});
