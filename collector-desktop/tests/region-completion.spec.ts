import { test, expect } from "@playwright/test";

test("manual refresh updates district and parent completion badges", async ({ page }) => {
  let completed = false;
  let requests = 0;
  await page.route("**/api/collection/regions?*", async (route) => {
    requests += 1;
    await route.fulfill({ json: { ok: true, stage: "links", regions: [{
      location_code: "440115", province: "广东省", city: "广州市", district: "南沙区",
      label: "广州市 南沙区", completed, status_label: completed ? "收集完成" : "待采集",
      counts: { total_progress: 12, exhausted_progress: completed ? 12 : 9, pending_progress: completed ? 0 : 3 },
    }] } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "筛选地区", exact: true }).click();
  await page.locator('.province-tab[data-province="广东省"]').click();
  await page.locator('.city-tab[data-city="广州市"]').click();
  const district = page.locator('.district-tab[data-location-code="440115"]');
  await expect(district).toContainText("待采集");
  await expect(district).toContainText("9/12");
  await expect(page.locator('.province-tab[data-province="广东省"]')).toContainText("待采集");
  const before = requests;
  completed = true;
  await page.getByRole("button", { name: "刷新数据", exact: true }).click();
  await expect.poll(() => requests).toBeGreaterThan(before);
  await expect(district).toContainText("收集完成");
  await expect(district).toContainText("12/12");
  await expect(page.locator('.city-tab[data-city="广州市"]')).toContainText("收集完成");
  await expect(page.locator('.province-tab[data-province="广东省"]')).toContainText("收集完成");
});
