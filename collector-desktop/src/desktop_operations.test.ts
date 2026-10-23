import assert from "node:assert/strict";
import { test } from "node:test";
import { count, epoch, reason, renderOperations, renderReceipt, operationsFreshness } from "./desktop_operations_view.ts";
import { renderOperationsConfig } from "./desktop_operations_config.ts";
import { renderOverview } from "./desktop_overview.ts";

const fixture = () => ({
  status: { statistics: { valid: true, stale: false }, seed_scan_job_pending: 12, seed_scan_job_completed: 50,
    collection_scopes: { seed: { last_status: "running", paused: true, pause_reason: "captcha_solver" },
      detail: { manual_required: true, last_failure_reason: "challenge_retry_exhausted", node_solver_blocked_attempts: 7 } },
    captcha_solver: { delegated_to_node_solver: true, manual_retry_next_epoch: 1792773000 } },
  modules: { links: { unique_items: 1234, total: 9999 }, details: { captured: 1000, pending: 234, failed: 3 }, analysis: { pending: 100, finalized: 900 } },
});

test("operations preserves queue units, missing counters and independent scope states", () => {
  const html = renderOperations(fixture(), 1000, false, 2000);
  assert.match(html, /链接扫描任务/); assert.match(html, /1,234/); assert.match(html, /9,999/);
  assert.match(html, /<td>—<\/td>/); assert.match(html, /挑战处理中/); assert.match(html, /需要认证 \/ 介入/);
  assert.match(html, /本轮挑战尝试已耗尽/); assert.match(html, /不是 PC2 本地 solver 冷却/);
  assert.match(html, /包含可重试失败/);
  assert.equal(reason("repeated_solver_failures"), "节点连续求解失败；等待退避或人工介入");
});
test("empty overview never claims healthy or zero backlog", () => {
  const html = renderOperations(null, 0, false);
  assert.match(html, /尚未收到/); assert.doesNotMatch(html, /未报告挑战|NAS 快照已接收/);
  assert.match(renderOperations({}, 1000, false, 2000), /状态未上报/);
});
test("invalid statistics suppress all queue counts while stale counts remain clearly historical", () => {
  const data = fixture(); data.status.statistics.valid = false;
  const html = renderOperations(data, 1000, false, 2000);
  assert.match(html, /统计不可用/); assert.doesNotMatch(html, /1,234|9,999|<td>234</);
  data.status.statistics.valid = true; data.status.statistics.stale = true;
  assert.match(renderOperations(data, 1000, false, 2000), /快照陈旧/);
});
test("failure and age mark stale without treating expired retry as success", () => {
  assert.equal(operationsFreshness(fixture(), 1000, false, 2000).warning, false);
  assert.equal(operationsFreshness(fixture(), 1000, true, 2000).warning, true);
  assert.equal(operationsFreshness(fixture(), 1000, false, 92000).warning, true);
  assert.match(renderOperations(fixture(), 1000, true, 2000), /是否执行以新状态为准/);
});
test("numbers and timestamps fail closed on non-numeric, negative and non-finite inputs", () => {
  for (const value of [undefined, null, false, "12", -1, NaN, Infinity, 1.5]) assert.equal(count(value), "—");
  assert.equal(count(0), "0");
  for (const value of [null, false, "12", -1, Infinity, 1e20]) assert.equal(epoch(value), "—");
});
test("projection never renders raw target, unknown errors or secret fields", () => {
  const data = fixture();
  Object.assign(data.status.collection_scopes.detail, { last_failure_reason: "Bearer SECRET_PRIVATE", last_request: { target_url: "https://secret.invalid/?key=PRIVATE" } });
  Object.assign(data, { api_key: "SECRET_PRIVATE", auth_watcher: { last_error: "SECRET_PRIVATE" } });
  const html = renderOperations(data, 1000, false, 2000);
  assert.doesNotMatch(html, /SECRET_PRIVATE|secret.invalid/);
  assert.match(html, /未分类原因/); assert.equal(reason("__proto__"), "未分类原因（原始内容不展示）");
});
test("receipt validates identifiers and allowlists results instead of exposing raw exceptions", () => {
  const html = renderReceipt({ id: '<img src=x onerror="bad">', status: "unknown", result: "SECRET_PRIVATE" });
  assert.match(html, /禁止重复提交/); assert.doesNotMatch(html, /<img|SECRET_PRIVATE/);
  assert.match(renderReceipt({ id: "request-123", status: "succeeded", result: "workers_ready" }), /不等于业务成功/);
});
test("configuration summary only uses effective values, never desired or credentials", () => {
  const html = renderOperationsConfig({ revision: 4, available: true, api_key_configured: true,
    effective: { workers: { links: 1, details: 3, analysis: 4 }, ai: { model: "gpt-6.1-sol", allow_gpt: true, reasoning_effort: "low", api_key: "SECRET_PRIVATE", base_url: "https://u:PRIVATE@host/" } },
    desired: { ai: { model: "not-yet-effective" } }, request: { status: "applying" } });
  assert.match(html, /gpt-6.1-sol/); assert.match(html, /已开启/); assert.match(html, /1 \/ 3 \/ 4/);
  assert.match(html, /正在应用/); assert.doesNotMatch(html, /SECRET_PRIVATE|not-yet-effective|u:PRIVATE/);
});
test("missing config does not adopt local defaults or claim GPT disabled", () => {
  const html = renderOperationsConfig({});
  assert.match(html, /未上报/); assert.doesNotMatch(html, /已关闭|deepseek|gpt-/);
});
test("unknown restart receipts lock both overview and operations source control", () => {
  const html = renderOverview({ engine_restart: { available: true, request: { status: "unknown" } } }, "运行中");
  assert.match(html, /id="engineRestartButton"[^>]+data-available="false"/);
});
