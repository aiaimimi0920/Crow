// Isolated local fixtures: never forwards requests to NAS, PC2 or an AI provider.
export default async function applyRaceSmoke(page, { origin }) {
  const checks = [];
  const check = (value, name) => { if (!value) throw new Error(name); checks.push(name); };
  await page.context().route("**/*", (route) => route.request().url().startsWith(`${origin}/`) ? route.continue() : route.abort());
  const config = {
    workers: { links: 1, details: 3, analysis: 4 },
    intervals: { links: 30, details: 30, analysis: 5, links_idle: 60, details_idle: 60, analysis_idle: 60, success_delay: 6, failure_delay: 15 },
    retries: { detail_item_attempts: 3, analysis_item_attempts: 3, detail_batch_attempts: 30, analysis_batch_attempts: 20, ai_attempts: 2 },
    ai: { base_url: "https://ai.example.invalid/v1", model: "fixture-model", timeout_seconds: 180 },
  };
  let state = { ok: true, revision: 1, available: true, effective: config, api_key_configured: true, request: null };
  let releasePost;
  let enteredPost;
  let postEntered = new Promise((resolve) => { enteredPost = resolve; });
  let gate = new Promise((resolve) => { releasePost = resolve; });
  let dropResponse = false;
  let submissions = 0;
  await page.route("**/api/collection/settings**", async (route) => {
    if (route.request().method() === "GET") return route.fulfill({ json: state });
    submissions += 1;
    const body = route.request().postDataJSON();
    state = { ...state, revision: state.revision + 1, effective: body.config,
      request: { id: body.request_id, revision: state.revision + 1, status: "succeeded" } };
    enteredPost();
    await gate;
    if (dropResponse) return route.abort("failed");
    return route.fulfill({ json: { ok: true, request: state.request } });
  });
  await page.goto(origin);
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.locator("#openSettings").click();
  await page.locator("#runtimeSettings summary").click();
  await page.locator("#settingsControlBase").fill(origin);
  await page.locator("#restartToken").fill("synthetic-token-00001");
  await page.locator("#settingsApply").click();
  await page.locator('#settingsApplyDialog button[value="confirm"]').click();
  await postEntered;
  await page.locator("#restartToken").fill("synthetic-replacement-token");
  await page.locator("#restartToken").press("Tab");
  check(await page.locator("#settingsApply").isDisabled(), "credential change cannot unlock an in-flight POST");
  check(await page.locator('[id="setting-workers.details"]').isEnabled(), "in-flight POST does not freeze draft editing");
  releasePost();
  await page.waitForFunction(() => !document.querySelector("#settingsStatusRefresh").disabled);
  check((await page.locator("#settingsStatus").textContent()).includes("连接或授权已变化"), "stale POST receipt cannot overwrite new credential state");
  await page.locator("#settingsStatusRefresh").click();
  await page.locator("#settingsStatus").filter({ hasText: "应用成功" }).waitFor();
  check(submissions === 1, "credential changes never automatically replay a POST");
  dropResponse = true;
  postEntered = new Promise((resolve) => { enteredPost = resolve; });
  gate = new Promise((resolve) => { releasePost = resolve; });
  await page.locator("#settingsApply").click();
  await page.locator('#settingsApplyDialog button[value="confirm"]').click();
  await postEntered;
  releasePost();
  await page.locator("#settingsStatus").filter({ hasText: "提交结果需刷新确认" }).waitFor();
  check(await page.locator("#settingsApply").isDisabled(), "lost POST response blocks duplicate apply");
  await page.locator("#settingsStatus").filter({ hasText: "应用成功" }).waitFor({ timeout: 10000 });
  check(await page.locator("#settingsApply").isEnabled(), "automatic status polling reconciles a lost POST response");
  check(submissions === 2, "response loss does not cause POST replay");
  return { checks };
}
