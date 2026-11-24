import type { Config } from "./desktop_settings_contract.ts";

// Non-secret defaults sampled from the configured PC2 deployment, not UI fixtures.
export const defaultsObservedAt = "2026-11-24T09:30:00Z";
export const localCollectionDefaults: Config = {
  workers: { links: 1, details: 3, analysis: 4 },
  intervals: {
    links: 30, details: 30, analysis: 5,
    links_idle: 60, details_idle: 60, analysis_idle: 60,
    success_delay: 6, failure_delay: 15,
  },
  retries: {
    detail_item_attempts: 3, analysis_item_attempts: 3,
    detail_batch_attempts: 30, analysis_batch_attempts: 20, ai_attempts: 2,
  },
  ai: { base_url: "http://192.168.15.20:4200/v1", model: "glm-5-2", timeout_seconds: 180 },
};
