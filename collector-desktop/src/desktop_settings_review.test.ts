import assert from "node:assert/strict";
import test from "node:test";
import { localCollectionDefaults } from "./collection_defaults.ts";
import { settingsChanges, settingsStateSummary } from "./desktop_settings_review.ts";

test("review exposes stale AI address, model and GPT differences without credentials", () => {
  const live = structuredClone(localCollectionDefaults);
  live.ai = { ...live.ai, base_url: "https://live.invalid/v1", model: "gpt-6.1-sol", allow_gpt: true };
  const changes = settingsChanges(live, localCollectionDefaults);
  assert.match(changes, /Base URL.*https:\/\/live.invalid\/v1/);
  assert.match(changes, /模型路由.*gpt-6.1-sol/);
  assert.match(changes, /允许使用 GPT: true → false/);
  assert.equal(settingsChanges(live, structuredClone(live)), "");
  const gptDisabledOnly = structuredClone(live);
  delete gptDisabledOnly.ai.allow_gpt;
  assert.match(settingsChanges(live, gptDisabledOnly), /仅使用已配置的非 GPT 后备候选/);
});

test("receipt identifies its own revision instead of claiming the draft was applied", () => {
  const summary = settingsStateSummary({ available: true, revision: 7, request: { revision: 6, status: "succeeded" } });
  assert.match(summary, /当前配置版本 7/);
  assert.match(summary, /最近操作（版本 6）/);
  assert.doesNotMatch(summary, /参数已应用/);
});
