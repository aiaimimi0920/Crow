import assert from "node:assert/strict";
import { test } from "node:test";
import { authScopeChallenge, authScopeState, authScopeTarget } from "./desktop_auth_scope.ts";

test("stage statuses do not inherit the other stage or aggregate challenge", () => {
  const value = { status: { captcha_solver: { manual_required: true }, collection_scopes: {
    seed: { manual_required: true, challenge_id: "seed" }, detail: { paused: false, challenge_id: "detail" },
  } } };
  assert.equal(authScopeChallenge(value, "seed"), true);
  assert.equal(authScopeChallenge(value, "detail"), false);
  assert.equal(authScopeState(value, "detail")?.challenge_id, "detail");
  assert.equal(authScopeChallenge({}, "detail"), null);
});

test("detail authentication never silently falls back to a list page", () => {
  const value = { status: { collection_scopes: { detail: { last_request: { target_url: "https://sf.taobao.com/list/1.htm" } } } } };
  assert.equal(authScopeTarget(value, "detail"), "");
  assert.equal(authScopeTarget(value, "detail", "12345"), "https://sf-item.taobao.com/sf_item/12345.htm");
  assert.equal(authScopeTarget(value, "detail", "1/../../"), "");
  const seed = new URL(authScopeTarget({}, "seed"));
  assert.equal(seed.protocol, "https:");
  assert.equal(seed.hostname, "sf.taobao.com");
  assert.ok(seed.pathname.startsWith("/list/"));
});
