import { test, expect } from "@playwright/test";

test("native alias conflict blocks initial and timed HTTP until explicit apply", async ({ page, baseURL }) => {
  let requests = 0;
  const browserErrors: string[] = [];
  page.on("pageerror", error => browserErrors.push(error.message));
  await page.clock.install();
  await page.route("**/api/**", async route => {
    requests += 1;
    await route.fulfill({ json: {} });
  });
  await page.addInitScript(() => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: {
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
      invoke: async (command: string) => {
        if (command === "default_api_base") {
          throw new Error("crow_configuration_alias_conflict:CROW_COLLECTOR_API_BASE,FAPAI_COLLECTOR_API_BASE");
        }
        throw new Error("Synthetic native action unavailable");
      },
    } });
  });
  await page.goto(baseURL!);
  await expect(page.locator("#connectionStatus")).toContainText("配置冲突");
  expect(requests).toBe(0);
  await page.clock.fastForward(600_001);
  expect(requests).toBe(0);
  await page.locator("#apiBase").fill(baseURL!);
  await page.locator("#applyApiBase").click();
  await expect.poll(() => requests).toBeGreaterThan(0);
  await expect(page.locator("#refresh")).toBeEnabled();
  const initial = requests;
  await page.clock.fastForward(60_001);
  await expect.poll(() => requests).toBeGreaterThan(initial);
  expect(browserErrors).toEqual([]);
});

test("plain browser startup keeps its same-origin fallback", async ({ page, baseURL }) => {
  const destinations: string[] = [];
  await page.route("**/api/**", async route => {
    destinations.push(new URL(route.request().url()).origin);
    await route.fulfill({ json: {} });
  });
  await page.goto(baseURL!);
  await expect(page.locator("#apiBase")).toHaveValue(baseURL!);
  await expect.poll(() => destinations.length).toBeGreaterThan(0);
  expect(new Set(destinations)).toEqual(new Set([baseURL!]));
});
