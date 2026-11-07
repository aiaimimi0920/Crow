import { test, expect } from "@playwright/test";

test("zero unique growth and node failures remain truthful in both views", async ({ page, baseURL }, info) => {
  await page.context().route("**/*", (route) => route.request().url().startsWith(`${baseURL}/`) ? route.continue() : route.abort());
  await page.route("**/api/collection/overview", async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.status.statistics = { valid: true, stale: false, minute_delta: [0, 0, 0], window_seconds: 69 };
    data.status.collection_scopes = {
      seed: { paused: false, manual_required: false, last_status: "idle" },
      detail: { paused: true, manual_required: true, manual_only: true, last_status: "manual_required",
        node_solver_blocked: true, node_solver_blocked_reason: "repeated_solver_failures" },
    };
    await route.fulfill({ json: data });
  });
  await page.goto(baseURL!);
  await expect(page.locator("#cards")).toContainText("求解连续失败");
  await expect(page.locator(".metric-card .growth-line")).toHaveText(["+0", "+0", "+0"]);
  await expect(page.locator(".metric-card").first()).toContainText("近 69 秒采样 · 去重净增量；重复扫描不计新增");
  await expect(page.locator("#detailAuthButton")).toBeEnabled();
  await expect(page.locator(".auth-stage-row").first()).toContainText("未报告挑战");
  for (const width of [1120, 980, 720]) {
    await page.setViewportSize({ width, height: 760 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.screenshot({ path: info.outputPath("retry-blocked-overview.png"), fullPage: true });
  await page.locator("#openOperations").click();
  await expect(page.locator("#operationsSnapshot")).toContainText("求解连续失败");
  await expect(page.locator("#operationsSnapshot")).toContainText("PC2 下次尝试时间尚未上报，不代表正在求解");
  await expect(page.locator("#operationsDetailAuth")).toBeEnabled();
});

test("an unpaused challenge remains visible behind an empty top-level scope map", async ({ page, baseURL }) => {
  await page.context().route("**/*", (route) => route.request().url().startsWith(`${baseURL}/`) ? route.continue() : route.abort());
  await page.route("**/api/collection/overview", async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.status.collection_scopes = {};
    data.status.captcha_solver = {
      running: false, queued: false, paused: false, manual_required: false,
      scopes: {
        seed: { challenge_id: "fixture-active-challenge", paused: false, last_status: "idle" },
        detail: { challenge_id: null, paused: false, last_status: "idle" },
      },
    };
    await route.fulfill({ json: data });
  });
  await page.goto(baseURL!);
  await expect(page.locator(".auth-stage-row").first()).toContainText("待认证");
  await expect(page.locator(".auth-stage-row").last()).toContainText("未报告挑战");
  await expect(page.locator("#seedAuthButton")).toBeEnabled();
});
