// Isolated loopback fixtures only; no production control requests.
export default async function operationsSmoke(page, { origin, artifactDir }) {
  const checks = [], browserErrors = [];
  const check = (value, name) => { if (!value) throw new Error(name); checks.push(name); };
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.context().route("**/*", (route) => route.request().url().startsWith(`${origin}/`) ? route.continue() : route.abort());
  await page.clock.install();
  const fixture = (data) => page.request.post(`${origin}/__preview/state`, { data });
  const events = async () => (await (await page.request.get(`${origin}/__preview/state`)).json()).events;
  const refresh = async () => { await page.locator("#operationsRefresh").click(); await page.locator("#operationsRefresh:not([disabled])").waitFor(); };
  const config = {
    workers: { links: 1, details: 3, analysis: 4 },
    intervals: { links: 30, details: 30, analysis: 5, links_idle: 60, details_idle: 60, analysis_idle: 60, success_delay: 6, failure_delay: 15 },
    retries: { detail_item_attempts: 3, analysis_item_attempts: 3, detail_batch_attempts: 30, analysis_batch_attempts: 20, ai_attempts: 2 },
    ai: { base_url: "https://ai.example.invalid/v1", model: "gpt-6.1-sol", allow_gpt: true, reasoning_effort: "low", timeout_seconds: 180 },
  };
  let reads = 0;
  await page.route("**/api/collection/settings", (route) => {
    reads++;
    return route.fulfill({ json: { ok: true, available: true, revision: 4, effective: config,
      desired: { ai: { model: "not-effective-model" } }, api_key_configured: true, request: { id: "settings-fixture", status: "succeeded", updated: 1792770000 } } });
  });
  await fixture({ scenario: "normal", reset_events: true, challenge: true, restart: { available: true, request: null } });
  await page.setViewportSize({ width: 1120, height: 900 });
  await page.goto(origin);
  await page.locator("#items tr.item-row").first().waitFor();
  await page.locator("#openOperations").click();
  check(await page.locator("#operationsTitle").evaluate((node) => node === document.activeElement), "operations navigation moves focus to title");
  check(await page.locator("#collectionPage").isHidden(), "operations is a distinct page");
  check(await page.locator(".ops-table tbody tr").count() === 3, "all three queue stages visible");
  check((await page.locator("#operationsSnapshot").textContent()).includes("1,940"), "detail backlog rendered from actual fixture");
  check((await page.locator("#operationsSnapshot").textContent()).includes("状态未上报"), "missing scope is not healthy");
  check((await page.locator("#operationsSnapshot").textContent()).includes("不是 PC2 本地 solver 冷却"), "NAS and PC2 retry sources distinguished");
  await page.locator("#operationsQueue").focus();
  await page.clock.fastForward(61_000);
  await page.locator("#operationsRefresh:not([disabled])").waitFor();
  check(await page.locator("#operationsQueue").evaluate((node) => node === document.activeElement), "automatic refresh preserves keyboard table focus");
  check(await page.locator("#operationsRestart").isDisabled(), "operations restart also requires authorization");
  await page.locator("#operationsConfigRefresh").click();
  await page.locator("#operationsConfigStatus").filter({ hasText: "请先填写控制授权" }).waitFor();
  check(reads === 0, "unauthorized config refresh sends no request");
  await page.locator("#openSettings").click();
  await page.locator("#restartToken").fill("offline-fixture-operator-token-00001");
  await page.locator("#openOperations").click();
  await page.locator("#operationsConfigRefresh").click();
  await page.locator("#operationsConfig").filter({ hasText: "gpt-6.1-sol" }).waitFor();
  check((await page.locator("#operationsConfig").textContent()).includes("已开启"), "live GPT permission displayed");
  check(!(await page.locator("#operationsConfig").textContent()).includes("not-effective-model"), "desired config is not presented as effective");
  await page.locator('[data-settings-target="setting-ai.allow_gpt"]').click();
  check(await page.locator('[id="setting-ai.allow_gpt"]').evaluate((node) => node === document.activeElement), "GPT shortcut opens and focuses real authorized editor");
  check(await page.locator("#runtimeSettings").getAttribute("open") !== null, "runtime settings expanded");
  await page.locator('[id="setting-workers.details"]').fill("2");
  await page.locator("#openOperations").click();
  await page.locator("#operationsConfigRefresh").click();
  await page.locator("#operationsConfigRefresh:not([disabled])").waitFor();
  await page.locator('[data-settings-target="setting-workers.links"]').click();
  check(await page.locator('[id="setting-workers.details"]').inputValue() === "2", "summary refresh preserves unsaved draft");
  await page.locator("#openOperations").click();
  await page.locator("#operationsPause").click();
  await page.locator("#operationsPause").filter({ hasText: "开始采集" }).waitFor();
  await page.locator("#operationsPause").click();
  await page.locator("#operationsPause").filter({ hasText: "暂停采集" }).waitFor();
  check((await events()).some((event) => event.path.endsWith("/control/start")), "operations uses existing start control");
  check(!(await events()).some((event) => event.path.endsWith("/auth/complete")), "operations start never clears auth");
  await page.locator("#operationsSeedAuth").click();
  await page.locator("#authChallengeDialog[open]").waitFor();
  await page.keyboard.press("Escape");
  check(await page.locator("#operationsPage").isVisible(), "auth Escape closes dialog not operations page");
  await page.locator("#operationsRestart").click();
  await page.locator('#engineRestartDialog button[value="cancel"]').click();
  check(!(await events()).some((event) => event.path.endsWith("/control/restart")), "cancel on operations never restarts");
  await fixture({ restart: { available: true, request: { id: "unknown-restart", status: "unknown" } } });
  await refresh();
  check(await page.locator("#operationsRestart").isDisabled(), "unknown restart blocks resubmission even on browser transport");
  await page.locator("#operationsPage details summary").click();
  check((await page.locator("#operationsRestartReceipt").textContent()).includes("禁止重复提交"), "unknown receipt gives actionable explanation");
  await page.screenshot({ path: `${artifactDir}/operations-wide.png`, fullPage: true });
  await page.locator("#operationsConfig").scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${artifactDir}/operations-config.png`, fullPage: true });
  for (const width of [980, 720, 480]) {
    await page.setViewportSize({ width, height: 900 });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.querySelector("main").scrollWidth <= document.querySelector("main").clientWidth), `operations has internal scrolling at ${width}`);
  }
  await page.screenshot({ path: `${artifactDir}/operations-narrow.png`, fullPage: true });
  await fixture({ scenario: "error" });
  await refresh();
  check(await page.locator("#overviewNotice").isVisible(), "connection failure is visible outside collection page");
  check((await page.locator("#operationsFreshness").textContent()).includes("快照陈旧"), "failed refresh marks historical operations data stale");
  await page.screenshot({ path: `${artifactDir}/operations-offline.png`, fullPage: true });
  await page.keyboard.press("Escape");
  check(await page.locator("#collectionPage").isVisible(), "operations Escape returns to collection");
  await fixture({ scenario: "normal" });
  return { checks, browserErrors };
}
