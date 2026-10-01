import assert from "node:assert/strict";
import crypto from "node:crypto";
import test from "node:test";
import { buildUserscriptSource, loadUserscriptParts } from "../build-userscript.mjs";
import { dispatchFixture, extractFixture, restoreReviewedSource } from "./userscript-equivalence-support.mjs";

// Commit 9832ded2's complete program is 677d08411ed761d7b723534593ba2724dcb560699d2e9abaa3bcda24448483db.
// Only trailing whitespace inside the two extracted helpers is normalized;
// those helpers contain no multiline template literals. All other bytes remain.
const NORMALIZED_PRIOR_HASH = "54a336ca0d60af0eb6e55423e90bef04a4d4f20bbef4644193e531cf674e0653";

test("reversing helper extraction restores the reviewed program with helper trailing whitespace normalized", () => {
  const restored = restoreReviewedSource();
  assert.equal(crypto.createHash("sha256").update(restored).digest("hex"), NORMALIZED_PRIOR_HASH);
  assert.equal(loadUserscriptParts().length, 12);
  assert.notEqual(buildUserscriptSource(), restored, "helper extraction intentionally changes source placement");
});

for (const [label, url, options = {}] of [
  ["master", "https://sf.taobao.com/list/123.htm"],
  ["detail", "https://sf-item.taobao.com/sf_item/123.htm"],
  ["auto detail", "https://sf-item.taobao.com/sf_item/123.htm?auto_fix=1"],
  ["detail worker", "https://sf-item.taobao.com/sf_item/123.htm?auto_worker=1"],
  ["login", "https://login.taobao.com/member/login.jhtml"],
  ["security", "https://sec.taobao.com/punish"],
  ["standby halt", "https://sf.taobao.com/?__captcha_worker_master=1"],
  ["solver halt", "https://sf.taobao.com/list/123.htm?__captcha_solver_bg=1"],
  ["named worker halt", "https://login.taobao.com/", { name: "captcha_worker" }],
  ["manual popup", "https://sf.taobao.com/list/123.htm?__captcha_manual_popup=1"],
  ["sniff worker", "https://sf.taobao.com/list/123.htm?uni_mode=SNIFF_WORKER"],
  ["unrelated host", "https://attacker.test/"],
]) test(`full generated dispatcher preserves ${label} side effects and early return`, () => {
  const before = dispatchFixture(restoreReviewedSource(), url, structuredClone(options));
  const after = dispatchFixture(buildUserscriptSource(), url, structuredClone(options));
  assert.deepEqual(after, before);
  if (label.includes("halt")) {
    assert.ok(!after.logs.some((entry) => String(entry[0]).includes("Init Tab ID")));
    assert.ok(!after.events.some((entry) => entry[1] === "createDashboard"));
  }
  if (label === "master") assert.ok(after.events.some((entry) => entry[1] === "createDashboard"));
  if (label === "detail") assert.ok(after.timers.some((entry) => entry[2] === "createPanel"));
});

const encoded = (value) => encodeURIComponent(JSON.stringify(value));
const fixtures = [
  { url: "https://sf-item.taobao.com/sf_item/123.htm", body: "已成交\n标的物位置：浙江省杭州市西湖区春天花园\n建筑面积88.5平方米 二分之一产权\n杭州市人民法院 （2026）浙01执123号",
    nodes: { "h1": { innerText: "  测试\n 房源 " }, "#J_NoticeDetail": { innerText: "司法拍卖公告内容长于十个字符" } },
    scripts: [encoded({ key: "STATISTICS_INFO", dataSource: { applyNumber: 3, bidCount: 5, watchCount: 12 } }),
      encoded({ key: "BID_CONTROL", dataSource: { currentPrice: 123456, status: "succ", startTime: 1700000000000, endTime: 1700003600000 } }),
      encoded({ key: "AUCTION_RULE", dataSource: { bidRuleFields: [{ title: "保证金", texts: [{ preMsg: "20000元" }] }] } })] },
  { url: "https://paimai.taobao.com/pmp_item/fixture?id=456", title: "Fallback title", body: "成交价：￥1,234,567\n出价次数：9\n共有 4人出价\n建筑面积：66.8平方米 三分之一产权", stats: [{ textContent: "6人报名" }] },
  { url: "https://sf-item.taobao.com/sf_item/789.htm", body: "当前价：99\n产权面积40平米 25%产权", scripts: ["not-json", "%ZZ", ""] },
  { url: "https://sf-item.taobao.com/unknown", title: "无数据", body: "正文\n\n\n" + "长正文".repeat(1100) },
];
for (const [index, fixture] of fixtures.entries()) test(`DOM extraction fixture ${index} preserves all fields and fresh-page reads`, () => {
  const before = extractFixture(fixture, true), after = extractFixture(fixture);
  assert.deepEqual(after.extract(), before.extract());
  const result = after.extract();
  if (index === 0) {
    assert.equal(result.id, "123"); assert.equal(result["成交价格"], 123456);
    assert.equal(result["保证金"], 20000); assert.equal(result["产权份额比例"], 0.5);
    assert.equal(result["开拍时间"], "2023-11-14T22:13:20.000Z");
  }
  if (index === 1) { assert.equal(result.id, "456"); assert.equal(result["成交价格"], 1234567); }
  if (index === 3) { assert.equal(result.id, "unknown"); assert.equal(result.context.length, 3000); }
  before.document.body.innerText = after.document.body.innerText = "新页面正文\n建筑面积：77平方米";
  before.window.location.href = after.window.location.href = "https://sf-item.taobao.com/sf_item/900.htm";
  assert.deepEqual(after.extract(), before.extract());
  assert.equal(after.extract().id, "900");
});
