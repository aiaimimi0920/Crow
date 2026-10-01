import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import { authTargetScope } from "./desktop_auth_target.ts";
import { authScopeTarget } from "./desktop_auth_scope.ts";
import { object } from "./desktop_value.ts";

test("authentication scope uses the URL host and path, including challenge redirects", () => {
  assert.equal(authTargetScope("https://sf.taobao.com/list/123.htm?page=2"), "seed");
  assert.equal(authTargetScope("https://sf-item.taobao.com/sf_item/123.htm"), "detail");
  assert.equal(authTargetScope("https://sf-item.taobao.com//sf_item/123.htm/_____tmd_____/punish?x5step=1"), "detail");
  for (const value of [
    "https://sf-item.taobao.com.attacker.test/sf_item/123.htm",
    "https://sf-item.taobao.com@attacker.test/sf_item/123.htm",
    "https://attacker.test/?next=https://sf-item.taobao.com/sf_item/123.htm",
    "https://attacker.test/#/sf_item/123.htm",
    "https://sf.taobao.com/?next=/sf_item/123.htm",
    "https://sf.taobao.com/?next=/list/123.htm",
    "https://user:password@sf-item.taobao.com/sf_item/123.htm",
    "https://sf-item.taobao.com:8443/sf_item/123.htm",
    "javascript://sf-item.taobao.com/sf_item/123.htm",
    "https://[bad", "", null,
  ]) assert.equal(authTargetScope(value), null, String(value));
});

test("a detail target cannot carry a seed URL in its query to enter the seed scope", () => {
  const value = { status: { collection_scopes: { seed: { last_request: {
    target_url: "https://sf-item.taobao.com/sf_item/123.htm?next=https://sf.taobao.com/list/1.htm",
  } } } } };
  const selected = new URL(authScopeTarget(value, "seed"));
  assert.equal(selected.hostname, "sf.taobao.com");
  assert.ok(selected.pathname.startsWith("/list/"));
  assert.equal(selected.searchParams.has("next"), false);
});

test("runtime status bypasses a detail-only pause only for a genuine detail target", () => {
  const source = fs.readFileSync(new URL("./desktop_collection_views.ts", import.meta.url), "utf8");
  const body = source.slice(source.indexOf("export function runtimeStateFromOverview"), source.indexOf("export async function loadOverview"))
    .replace("export function", "function")
    .replace("(data: CollectionRecord): string", "(data)");
  const runtime = vm.runInNewContext(body + ";runtimeStateFromOverview", { object, authTargetScope });
  const value = (url: string) => ({ status: { seed_scan_job_pending: 1,
    captcha_solver: { manual_required: true, last_request: { target_url: url } },
  } });
  assert.equal(runtime(value("https://sf-item.taobao.com/sf_item/123.htm")), "运行中");
  for (const url of [
    "https://sf-item.taobao.com.attacker.test/sf_item/123.htm",
    "https://attacker.test/?next=https://sf-item.taobao.com/sf_item/123.htm",
    "https://attacker.test/#/sf_item/123.htm",
    "https://sf.taobao.com/list/123.htm", "https://[bad",
  ]) assert.equal(runtime(value(url)), "待认证", url);
  assert.equal(runtime({ runtime_state: "explicit" }), "explicit");
  assert.equal(runtime({ status: { paused: true } }), "暂停中");
});
