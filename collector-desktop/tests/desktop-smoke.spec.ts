import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import authSmoke from "../../tools/test/collector_auth_ui_smoke.mjs";
import collectionSmoke from "../../tools/test/collector_collection_ui_smoke.mjs";
import settingsSmoke from "../../tools/test/collector_settings_ui_smoke.mjs";
import operationsSmoke from "../../tools/test/collector_operations_ui_smoke.mjs";

for (const [name, run] of Object.entries({ collection: collectionSmoke, authentication: authSmoke, settings: settingsSmoke, operations: operationsSmoke })) {
  test(name, async ({ page, baseURL }, info) => {
    page.setDefaultTimeout(10_000);
    const artifactDir = info.outputPath("screenshots");
    await mkdir(artifactDir, { recursive: true });
    const result = await run(page, { origin: baseURL!, artifactDir });
    expect(result.browserErrors).toEqual([]);
    expect(result.checks.length).toBeGreaterThan(10);
  });
}
