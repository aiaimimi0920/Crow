// Synthetic native bridge only; never opens production browser or sends cookies.
export default async function authSmoke(page, { origin, artifactDir }) {
  const checks = [];
  const errors = [];
  const check = (condition, name) => { if (!condition) throw new Error(name); checks.push(name); };
  page.on("pageerror", (error) => errors.push(error.message));
  await page.context().route("**/*", (route) => route.request().url().startsWith(`${origin}/`) ? route.continue() : route.abort());
  await page.request.post(`${origin}/__preview/state`, { data: { scenario: "normal", reset_events: true, challenge: false } });
  await page.route("**/api/collection/overview", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    payload.status.captcha_solver.scopes.detail = { last_request: { target_url: "https://sf-item.taobao.com/sf_item/123456.htm" } };
    return route.fulfill({ json: payload });
  });
  await page.addInitScript((base) => {
    window.__nativeCalls = [];
    window.__nativeResult = { phase: "ready_for_human", target_id: "fixture-selected" };
    window.__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
      invoke: async (command, args) => {
        if (command === "default_api_base") return base;
        if (command !== "desktop_auth_action") throw new Error(`Unexpected native command: ${command}`);
        window.__nativeCalls.push(args.request);
        if (window.__nativeReject) throw new Error("synthetic bridge unavailable");
        if (window.__nativeHold) await new Promise((resolve) => { window.__releaseNative = resolve; });
        return JSON.parse(JSON.stringify(window.__nativeResult));
      },
    };
  }, origin);
  await page.setViewportSize({ width: 1120, height: 760 });
  await page.clock.install();
  await page.goto(origin);
  await page.locator("#items tr.item-row").first().waitFor();
  check(await page.locator("#detailAuthButton").isEnabled(), "native auth can start without a reported PC2 challenge");
  await page.locator("#detailAuthButton").click();
  const dialog = page.locator("#authChallengeDialog");
  check((await dialog.locator("button").allTextContents()).map((text) => text.trim()).join() === "在常用 Edge 中认证,打开专用认证浏览器,已完成挑战", "both authentication sources are explicit");
  check(await dialog.locator("h1,h2,h3,input,iframe").count() === 0, "no secondary headings descriptions URL editor or embedded challenge");
  check(await page.evaluate(() => window.__nativeCalls.length) === 0, "dialog itself never opens browser or pauses collection");
  await page.screenshot({ path: `${artifactDir}/auth-dialog.png` });
  await page.locator("#authChallengeReload").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "挑战页面已打开" }).waitFor();
  check(await page.evaluate(() => window.__nativeCalls[0].action) === "open", "explicit open reaches native bridge");
  check(await page.evaluate(() => window.__nativeCalls[0].target_url) === "https://sf-item.taobao.com/sf_item/123456.htm", "detail challenge opens its actual item, not an unrelated list");
  await page.evaluate(() => { window.__nativeResult = { phase: "pending_human", code: "session_not_reusable", recovery_id: "fixture-recovery" }; });
  await page.locator("#authChallengeResume").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "尚未通过复用验证" }).waitFor();
  check(await dialog.isVisible(), "unverified session stays open without false start failure");
  check(await page.evaluate(() => window.__nativeCalls[1].target_id) === "fixture-selected", "completion binds browser target identity");
  await page.evaluate(() => { window.__nativeResult = { phase: "pending_pc2", code: "pc2_receiving", recovery_id: "fixture-recovery" }; });
  await page.locator("#authChallengeResume").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "等待 PC2" }).waitFor();
  check(await dialog.isVisible() && await page.locator("#authChallengeReload").isDisabled(), "submitted snapshot waits for PC2, cannot reopen mid-transfer");
  const waitingText = await page.locator("#authChallengeStatus").textContent();
  await page.evaluate(() => { window.__nativeHold = true; });
  await page.locator("#authChallengeResume").click();
  check(await page.locator("#authChallengeStatus").textContent() === waitingText, "status query preserves acknowledged stage instead of flashing receiving text");
  await page.evaluate(() => { window.__nativeHold = false; window.__releaseNative(); });
  await page.waitForFunction(() => !document.getElementById("authChallengeResume").disabled);
  for (const [code, text] of [["pc2_importing", "正在导入会话"], ["pc2_restarting", "正在重启认证浏览器"]]) {
    await page.evaluate((code) => { window.__nativeResult = { phase: "pending_pc2", code, recovery_id: "fixture-recovery" }; }, code);
    await page.locator("#authChallengeResume").click();
    await page.locator("#authChallengeStatus").filter({ hasText: text }).waitFor();
    check(await dialog.isVisible(), `${code} is acknowledged without false completion`);
  }
  await page.evaluate(() => { window.__nativeReject = true; });
  await page.locator("#authChallengeResume").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "认证同步未完成" }).waitFor();
  check(await page.evaluate(() => window.__nativeCalls.at(-1).action) === "status", "pending retry polls status instead of recapturing");
  await page.evaluate(() => { window.__nativeReject = false; window.__nativeResult = { phase: "pending_pc2", code: "pc2_verifying", recovery_id: "fixture-recovery" }; });
  await page.locator("#authChallengeResume").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "正在确认采集恢复" }).waitFor();
  check(await dialog.isVisible(), "PC2 imported cookies is not yet success");
  await page.screenshot({ path: `${artifactDir}/auth-pending.png` });
  await page.keyboard.press("Escape");
  await page.locator("#detailAuthButton").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "正在确认采集恢复" }).waitFor();
  check(await page.evaluate(() => window.__nativeCalls.at(-1).action) === "status", "reopened dialog preserves recovery identity");
  const beforeLongWait = await page.evaluate(() => window.__nativeCalls.length);
  await page.clock.runFor(300_000);
  check(await page.evaluate(() => window.__nativeCalls.length) > beforeLongWait + 95, "long PC2 verification keeps polling instead of silently stopping after 90 attempts");
  await page.clock.runFor(610_000);
  await page.locator("#authChallengeStatus").filter({ hasText: "已停止自动查询" }).waitFor();
  const afterLimit = await page.evaluate(() => window.__nativeCalls.length);
  await page.clock.runFor(60_000);
  check(await page.evaluate(() => window.__nativeCalls.length) === afterLimit, "automatic polling stops at the wall-clock limit");
  await page.locator("#authChallengeResume").click();
  check(await page.evaluate(() => window.__nativeCalls.at(-1).action) === "status", "manual query after timeout never republishes cookies");
  check(await dialog.isVisible(), "polling timeout is neither server failure nor success");
  await page.evaluate(() => { window.__nativeResult = { phase: "succeeded", recovery_id: "fixture-recovery" }; });
  await page.locator("#authChallengeResume").click();
  await page.locator("#authChallengeDialog:not([open])").waitFor({ state: "attached" });
  check(!await dialog.isVisible(), "only confirmed recovery closes dialog");
  await page.evaluate(() => { window.__nativeResult = { phase: "ready_for_human", code: "edge_ready", target_id: "edge:fixture" }; });
  await page.locator("#detailAuthButton").click();
  await page.locator("#authChallengeEdge").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "Edge 认证扩展" }).waitFor();
  const edgeRequest = await page.evaluate(() => window.__nativeCalls.at(-1));
  check(edgeRequest.browser === "edge" && edgeRequest.action === "open", "Edge opens through explicit native adapter");
  await page.locator("#authChallengeEdge").click();
  await page.waitForFunction((old) => window.__nativeCalls.at(-1).request_id !== old, edgeRequest.request_id);
  check(await page.evaluate(() => window.__nativeCalls.at(-1).request_id) !== edgeRequest.request_id, "new Edge authentication cannot reuse an old durable job");
  await page.evaluate(() => { window.__nativeResult = { phase: "pending_pc2", code: "pc2_receiving", recovery_id: "shared-auth-" + "e".repeat(32), shared: true }; });
  await page.locator("#authChallengeResume").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "等待 PC2" }).waitFor();
  check(await page.evaluate(() => window.__nativeCalls.at(-1).browser) === "edge", "completion preserves Edge source");
  check(await page.locator("#authChallengeEdge").isDisabled(), "Edge cannot replace an in-flight snapshot");
  const events = (await (await page.request.get(`${origin}/__preview/state`)).json()).events;
  check(!events.some((event) => /control\/pause|auth\/complete|report_captcha/.test(event.path)), "no fake resume or background solver HTTP calls");
  check(errors.length === 0, `no browser exceptions: ${errors.join("; ")}`);
  return { checks, browserErrors: errors };
}
