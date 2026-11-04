import assert from "node:assert/strict";
import { test } from "node:test";
import { challengeActive, minuteGrowth, operatorPaused, renderOverview, resetOverviewHistory, uniqueCounts } from "./desktop_overview.ts";

test("unique counts do not use link occurrences", () => {
  assert.deepEqual(uniqueCounts({ modules: { links: { total: 900, unique_items: 100 }, details: { captured: 80 }, analysis: { finalized: 50 } } }), [100, 80, 50]);
});

test("NAS samples survive a new window, and failed refreshes are not live growth", () => {
  resetOverviewHistory();
  const data = { modules: { links: { unique_items: 100 }, details: { captured: 80 }, analysis: { finalized: 50 } },
    status: { statistics: { valid: true, stale: false, minute_delta: [7, 4, 2], window_seconds: 61 } } };
  const html = renderOverview(data, "运行中", 0);
  assert.match(html, />\+7</);
  assert.match(html, /近 61 秒采样/);
  assert.doesNotMatch(html, /等待分钟采样/);
  data.status.statistics.stale = true;
  const stale = renderOverview(data, "运行中", 1000);
  assert.match(stale, /统计暂未更新/);
  assert.doesNotMatch(stale, />\+7</);
  data.status.statistics.valid = false;
  assert.ok(uniqueCounts(data).every(Number.isNaN));
});

test("manual refreshes cannot masquerade as minute growth", () => {
  resetOverviewHistory();
  assert.deepEqual(minuteGrowth([100, 80, 50], 0), [null, null, null]);
  assert.deepEqual(minuteGrowth([103, 81, 50], 10_000), [null, null, null]);
  assert.deepEqual(minuteGrowth([110, 85, 52], 60_000), [10, 5, 2]);
  assert.deepEqual(minuteGrowth([112, 87, 53], 70_000), [9, 6, 3]);
  assert.deepEqual(minuteGrowth([120, 90, 60], 160_000), [null, null, null]);
});

test("disconnects resets and invalid counters never invent positive growth", () => {
  resetOverviewHistory();
  minuteGrowth([100, 80, 50], 0);
  assert.deepEqual(minuteGrowth([90, NaN, 50], 60_000), [-10, null, 0]);
  resetOverviewHistory();
  assert.deepEqual(minuteGrowth([300, 100, 60], 120_000), [null, null, null]);
});

test("active challenge is independent from runtime and historic challenge rate", () => {
  assert.equal(challengeActive({ runtime_state: "运行中", status: { captcha_solver: { scopes: { detail: { manual_required: true } } } } }), true);
  assert.equal(challengeActive({ status: { captcha_solver: { running: true } } }), true);
  assert.equal(challengeActive({ challenge_metrics: { recent_challenge_hit_rate: 1 }, status: { captcha_solver: { paused: true, pause_reason: "operator" } } }), false);
  assert.equal(challengeActive({ runtime_state: "待认证" }), null);
});

test("toggle follows operator pause, not whether a detail challenge coexists", () => {
  assert.equal(operatorPaused({ status: { operator_paused: false, paused: true } }), false);
  assert.equal(operatorPaused({ status: { operator_paused: true, paused: true } }), true);
  assert.equal(operatorPaused({ status: { paused: true, captcha_solver: { pause_reason: "manual_required" } } }), false);
});

test("render has five cells, separate auth and restart, escaped state and no diagnostics", () => {
  resetOverviewHistory();
  const html = renderOverview({ status: { operator_paused: true, captcha_solver: {} } }, '<img src=x onerror="bad">', 0);
  assert.equal((html.match(/class="card /g) || []).length, 5);
  assert.match(html, /开始采集/);
  assert.doesNotMatch(html, /id="(?:seed|detail)AuthButton"[^>]+disabled/);
  assert.match(html, /id="engineRestartButton"[^>]+disabled/);
  assert.match(html, /&lt;img/);
  assert.doesNotMatch(html, /挑战触发率|链接出现次数|watcher-card/);
});

test("manual auth remains available with active, absent or unknown challenges", () => {
  for (const status of [{}, { captcha_solver: {} }, { captcha_solver: { manual_required: true } },
    { operator_paused: true, captcha_solver: { paused: true, pause_reason: "operator" } }]) {
    const html = renderOverview({ status }, "待认证");
    for (const scope of ["seed", "detail"]) {
      assert.ok(html.includes(`id="${scope}AuthButton"`));
      assert.doesNotMatch(html, new RegExp(`id="${scope}AuthButton"[^>]*disabled`));
    }
  }
});

test("zero unique growth exposes its window and does not claim workers are idle", () => {
  const html = renderOverview({ status: { statistics: { valid: true, stale: false, minute_delta: [0, 0, 0], window_seconds: 69 },
    collection_scopes: { seed: { paused: false }, detail: { paused: true, manual_required: true, manual_only: true,
      node_solver_blocked: true, node_solver_blocked_reason: "repeated_solver_failures" } } } }, "待认证");
  assert.match(html, />\+0</);
  assert.match(html, /<div class="label">近 69 秒采样 · 去重净增量；重复扫描不计新增<\/div>/);
  assert.match(html, /求解连续失败/);
  assert.match(html, /PC2 下次尝试时间尚未上报/);
  assert.match(html, /不证明 Worker 正常或持续产出/);
  assert.doesNotMatch(html, /10 分钟|正在求解|已恢复|id="detailAuthButton"[^>]*disabled/);
});
