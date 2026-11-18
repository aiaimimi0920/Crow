import { test, expect, type Page } from "@playwright/test";
import applyRaceSmoke from "../../tools/test/collector_settings_apply_race_smoke.mjs";

const live = {
  workers: { links: 1, details: 1, analysis: 1 },
  intervals: { links: 30, details: 30, analysis: 5, links_idle: 60, details_idle: 60, analysis_idle: 60, success_delay: 6, failure_delay: 15 },
  retries: { detail_item_attempts: 3, analysis_item_attempts: 3, detail_batch_attempts: 30, analysis_batch_attempts: 20, ai_attempts: 2 },
  ai: { base_url: "http://127.0.0.1:4200/v1", model: "gpt-6.1-sol", timeout_seconds: 180, allow_gpt: true, reasoning_effort: "low" },
};

async function setup(page: Page, baseURL: string, stale = false) {
  await page.route("**/*", route => route.request().url().startsWith(baseURL + "/") ? route.continue() : route.abort());
  await page.addInitScript(({ baseURL, live, stale }) => {
    const origin = "https://control.invalid:18443";
    if (stale && !localStorage.getItem("fixture-draft-created")) {
      const edited = structuredClone(live);
      edited.ai.base_url = "http://127.0.0.1:8317/v1";
      localStorage.setItem(`crow.collection-settings.draft.v1:${baseURL}`, JSON.stringify({ version: 1, config: edited, baseline: { origin, revision: 6 } }));
      localStorage.setItem("fixture-draft-created", "true");
    }
    const fixture = { revision: 7, config: live, submissions: [] as Record<string, unknown>[] };
    Object.defineProperty(window, "settingsFixture", { value: fixture });
    Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
      invoke: async (command: string, args: { request?: { action: string; body: Record<string, unknown> } }) => {
        if (command === "default_api_base") return baseURL;
        if (command !== "desktop_settings_action") return null;
        const request = args.request!;
        if (request.action === "config") return { ok: true, configured: true, origin };
        if (request.action === "get") return { ok: true, available: true, revision: fixture.revision, effective: fixture.config, request: { revision: 6, status: "succeeded" } };
        if (request.action === "apply") {
          fixture.submissions.push(request.body);
          fixture.config = request.body.config as typeof live;
          fixture.revision++;
          return { ok: true, request: { id: request.body.request_id, revision: fixture.revision, status: "succeeded" } };
        }
        return { ok: false };
      },
    } });
  }, { baseURL, live, stale });
  await page.goto(baseURL);
  await page.locator("#openSettings").click();
  await page.locator("#runtimeSettings summary").click();
  await expect(page.locator("#settingsStatus")).toContainText("当前配置版本 7");
}

test("initial inventory populates actual values and GPT can be switched off alone", async ({ page, baseURL }) => {
  await setup(page, baseURL!);
  await expect(page.locator('[id="setting-ai.base_url"]')).toHaveValue(live.ai.base_url);
  await expect(page.locator('[id="setting-workers.analysis"]')).toHaveValue("1");
  await page.locator('[id="setting-ai.allow_gpt"]').uncheck();
  await page.locator("#settingsApply").click();
  await expect(page.locator("#settingsApplyChanges")).toContainText("允许使用 GPT: true → false");
  await page.locator('#settingsApplyDialog button[value="confirm"]').click();
  await expect(page.locator("#settingsStatus")).toContainText("应用成功");
  const submissions = await page.evaluate(() => (window as unknown as { settingsFixture: { submissions: { config: typeof live }[] } }).settingsFixture.submissions);
  expect(submissions).toHaveLength(1);
  expect(submissions[0].config.ai.model).toBe("gpt-6.1-sol");
  expect(submissions[0].config.ai.allow_gpt).toBeUndefined();
  expect(submissions[0].config.workers).toEqual(live.workers);
});

test("old draft survives version change and requires explicit difference confirmation", async ({ page, baseURL }) => {
  await setup(page, baseURL!, true);
  await expect(page.locator('[id="setting-ai.base_url"]')).toHaveValue("http://127.0.0.1:8317/v1");
  await expect(page.locator("#settingsConfigSource")).toContainText("尚未应用");
  await page.locator("#settingsApply").click();
  await expect(page.locator("#settingsApplyRevision")).toContainText("从 6 变为 7");
  await expect(page.locator("#settingsApplyChanges")).toContainText("4200/v1 → http://127.0.0.1:8317/v1");
  await page.locator('#settingsApplyDialog button[value="confirm"]').click();
  await expect(page.locator("#settingsStatus")).toContainText("应用成功");
  const bodies = await page.evaluate(() => (window as unknown as { settingsFixture: { submissions: { expected_revision: number }[] } }).settingsFixture.submissions);
  expect(bodies).toHaveLength(1);
  expect(bodies[0].expected_revision).toBe(7);
});

test("editing during confirmation cannot submit an unreviewed configuration", async ({ page, baseURL }) => {
  await setup(page, baseURL!);
  await page.locator("#settingsApply").click();
  await expect(page.locator("#settingsApplyDialog")).toBeVisible();
  await page.evaluate(() => {
    const field = document.getElementById("setting-ai.model") as HTMLInputElement;
    field.value = "deepseek-fixture";
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.locator('#settingsApplyDialog button[value="confirm"]').click();
  await expect(page.locator("#settingsStatus")).toContainText("确认期间编辑内容已变化");
  expect(await page.evaluate(() => (window as unknown as { settingsFixture: { submissions: unknown[] } }).settingsFixture.submissions.length)).toBe(0);
});

test("settings credential changes and lost POST responses never replay application", async ({ page, baseURL }) => {
  page.setDefaultTimeout(10_000);
  const result = await applyRaceSmoke(page, { origin: baseURL! });
  expect(result.checks).toHaveLength(7);
});
