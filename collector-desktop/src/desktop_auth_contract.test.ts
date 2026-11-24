import assert from "node:assert/strict";
import test from "node:test";
import { authResult, authWaitState, AUTH_POLL_LIMIT_MS } from "./desktop_auth_contract.ts";
import { localCollectionDefaults } from "./collection_defaults.ts";
import { DEFAULT_AUTH_CHALLENGE_URL, normalizeAuthChallengeUrl } from "./desktop_auth_target.ts";
import { AUTH_ACTIVE_CODES, AUTH_FAILURE_CODES, AUTH_MESSAGES, AUTH_TERMINAL_CODE } from "./auth_recovery_codes.generated.ts";

test("pending capture and pending PC2 receipts are never completion", () => {
  for (const phase of ["pending_human", "pending_pc2", "unavailable", "failed"]) {
    const result = authResult({ phase });
    assert.equal(result.completed, false);
    assert.ok(!result.message.includes("开始失败"));
  }
  assert.equal(authResult({ phase: "succeeded" }).completed, true);
});

test("unknown script output is not exposed and pending is actionable", () => {
  assert.equal(authResult({ phase: "unavailable", code: "secret-looking-error" }).message.includes("secret-looking"), false);
  assert.match(authResult({ phase: "pending_human", code: "session_not_reusable" }).message, /会话尚未通过/);
});

test("every Python recovery stage and failure has a safe desktop message", () => {
  for (const [codes, phase] of [[AUTH_ACTIVE_CODES, "pending_pc2"], [AUTH_FAILURE_CODES, "failed"]] as const) {
    for (const code of Object.values(codes)) {
      const result = authResult({ code, phase });
      assert.equal(result.message, AUTH_MESSAGES[code]);
      assert.equal(result.completed, false);
    }
  }
  assert.equal(authResult({ phase: "failed", code: AUTH_TERMINAL_CODE }).completed, false);
  assert.equal(authResult({ phase: "succeeded", code: AUTH_TERMINAL_CODE }).completed, true);
});

test("prototype names in untrusted receipt codes and phases use safe fallbacks", () => {
  const fallback = authResult({ phase: "unavailable" }).message;
  for (const code of ["__proto__", "constructor", "toString"]) {
    const result = authResult({ phase: code, code });
    assert.equal(result.message, fallback);
    assert.equal(result.completed, false);
    assert.match(authResult({ shared: true, phase: "failed", stage_results: { seed: { phase: "failed", code } } }).message, /链接：未确认恢复/);
  }
});

test("received, importing, restarting and verification have distinct truthful messages", () => {
  const codes = ["pc2_receiving", "pc2_importing", "pc2_restarting", "pc2_verifying"];
  const results = codes.map((code) => authResult({ phase: "pending_pc2", code }));
  assert.equal(new Set(results.map((result) => result.message)).size, 4);
  assert.ok(results.every((result) => !result.completed));
  assert.match(results[1].message, /已领取/);
  assert.match(results[2].message, /重启认证浏览器/);
  assert.match(authResult({ phase: "failed", code: "pc2_progress_timeout" }).message, /已接收.*超时/);
});

test("polling has a wall-clock limit, without inventing a server failure or success", () => {
  assert.equal(authWaitState(null, 0).poll, true);
  assert.equal(authWaitState(0, AUTH_POLL_LIMIT_MS - 1).poll, true);
  const limit = authWaitState(0, AUTH_POLL_LIMIT_MS);
  assert.equal(limit.poll, false);
  assert.match(limit.hint, /再次查询/);
  assert.match(limit.hint, /不代表认证成功/);
});

test("local defaults match current deployment without embedded secrets or fixture routes", () => {
  assert.deepEqual(localCollectionDefaults.workers, { links: 1, details: 3, analysis: 4 });
  assert.equal(localCollectionDefaults.ai.base_url, "http://192.168.15.20:4200/v1");
  assert.equal(localCollectionDefaults.ai.model, "glm-5-2");
  assert.equal(localCollectionDefaults.intervals.analysis, 5);
  assert.equal(localCollectionDefaults.retries.ai_attempts, 2);
  assert.ok(!JSON.stringify(localCollectionDefaults).match(/api_key|password|fixture|example.invalid/));
});

test("detail challenge stays bound to its item instead of silently opening the list", () => {
  assert.equal(normalizeAuthChallengeUrl("https://sf-item.taobao.com/sf_item/123456.htm/_____tmd_____/punish?x5secdata=discard"), "https://sf-item.taobao.com/sf_item/123456.htm");
  assert.equal(normalizeAuthChallengeUrl("https://sf.taobao.com/list/50025969.htm?location_code=330106&x5secdata=discard"), "https://sf.taobao.com/list/50025969.htm?location_code=330106&__captcha_solver_bg=1");
  for (const url of ["https://sf.taobao.com.attacker.invalid/list/1", "https://user:password@sf.taobao.com/list/1", "javascript:alert(1)"]) assert.equal(normalizeAuthChallengeUrl(url), DEFAULT_AUTH_CHALLENGE_URL);
});
