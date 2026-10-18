import { test, expect } from "@playwright/test";

test("manual refresh updates district and parent completion badges", async ({ page }) => {
  let completed = false;
  let requests = 0;
  await page.route("**/api/collection/regions?*", async (route) => {
    requests += 1;
    await route.fulfill({ json: { ok: true, stage: "links", regions: [{
      location_code: "440115", province: "广东省", city: "广州市", district: "南沙区",
      label: "广州市 南沙区", completed, status_label: completed ? "本轮完成" : "待采集",
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
  await expect(district).toContainText("本轮完成");
  await expect(district).toContainText("12/12");
  await expect(page.locator('.city-tab[data-city="广州市"]')).toContainText("本轮完成");
  await expect(page.locator('.province-tab[data-province="广东省"]')).toContainText("本轮完成");
});

test("browsing Bincheng does not mark queued districts as executing", async ({ page }) => {
  const writes: string[] = [];
  page.on("request", (request) => { if (request.method() === "POST") writes.push(request.url()); });
  await page.route("**/api/collection/regions?*", (route) => route.fulfill({ json: { ok: true, regions: [
    { location_code: "371602", province: "山东省", city: "滨州市", district: "滨城", status_label: "待继续", completed: false,
      counts: { total_progress: 12, exhausted_progress: 9, pending_progress: 3, active_progress: 0 } },
    { location_code: "371621", province: "山东省", city: "滨州市", district: "惠民", status_label: "本轮完成", completed: true,
      counts: { total_progress: 12, exhausted_progress: 12, active_progress: 0 } },
    { location_code: "371622", province: "山东省", city: "滨州市", district: "阳信", status_label: "采集中", completed: false,
      counts: { total_progress: 12, exhausted_progress: 1, active_progress: 1 } },
  ] } }));
  await page.goto("/");
  await page.getByRole("button", { name: "筛选地区", exact: true }).click();
  await page.locator('.province-tab[data-province="山东省"]').click();
  await page.locator('.city-tab[data-city="滨州市"]').click();
  const bincheng = page.locator('.district-tab[data-location-code="371602"]');
  await bincheng.click();
  await expect(bincheng).toHaveAttribute("aria-pressed", "true");
  await expect(bincheng).toContainText("待继续 9/12");
  await expect(bincheng.locator(".region-status.live")).toHaveCount(0);
  await expect(page.locator('.district-tab[data-location-code="371621"]')).toContainText("本轮完成 12/12");
  expect(writes).toEqual([]);
});
