import { defineConfig } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";

const port = 1436;
const output = resolve(process.env.CROW_TEST_OUTPUT_DIR || "../output/playwright", `quality-${Date.now()}-${randomUUID()}`);
const python = process.env.CROW_TEST_PYTHON || "python";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  outputDir: output,
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    browserName: "chromium",
    headless: true,
    channel: process.env.CROW_TEST_BROWSER_CHANNEL,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `"${python}" ../tools/test/collector_ui_preview.py --port ${port}`,
    url: `http://127.0.0.1:${port}/__preview/state`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
