import assert from "node:assert/strict";
import { test } from "node:test";
import { controlOrigin, groups, readConfig } from "./desktop_settings_contract.ts";

test("secret-bearing requests only use HTTPS or a loopback tunnel", () => {
  assert.equal(controlOrigin("https://nas.example.invalid/api"), "https://nas.example.invalid");
  assert.equal(controlOrigin("http://127.0.0.1:18001"), "http://127.0.0.1:18001");
  for (const value of ["http://192.168.15.200:8001", "https://user:key@example.invalid", "https://example.invalid?key=x", "file:///tmp/config"]) assert.throws(() => controlOrigin(value));
});

test("empty, fractional counters and excessive worker totals are rejected", () => {
  const values: Record<string, string> = {};
  for (const group of groups) for (const field of group.fields) values[`${group.key}.${field[0]}`] = field.length === 4 ? String(field[2]) : "fixture";
  values["ai.base_url"] = "https://ai.example.invalid/v1";
  const read = () => readConfig((key) => values[key]);
  assert.ok(read());
  values["workers.links"] = "1.5";
  assert.throws(read);
  values["workers.links"] = "2"; values["workers.details"] = "8"; values["workers.analysis"] = "8";
  assert.throws(read);
  values["workers.links"] = "";
  assert.throws(read);
});

test("GPT permission and effort roundtrip as typed settings, defaulting off", () => {
  const values: Record<string, string> = {};
  for (const group of groups) for (const field of group.fields) values[`${group.key}.${field[0]}`] = field.length === 4 ? String(field[2]) : "fixture";
  values["ai.base_url"] = "http://127.0.0.1:4200/v1";
  const read = () => readConfig((key) => values[key]);
  assert.equal(read().ai.allow_gpt, undefined);
  values["ai.model"] = "gpt-6.1-sol";
  assert.throws(read, /GPT/);
  values["ai.allow_gpt"] = "true";
  values["ai.reasoning_effort"] = "low";
  assert.equal(read().ai.allow_gpt, true);
  assert.equal(read().ai.reasoning_effort, "low");
  values["ai.allow_gpt"] = "false";
  assert.throws(read, /GPT/);
  values["ai.model"] = "deepseek-fixture";
  values["ai.reasoning_effort"] = "none";
  assert.equal(read().ai.allow_gpt, undefined);
  assert.equal(read().ai.reasoning_effort, undefined);
  values["ai.allow_gpt"] = "1";
  assert.throws(read, /布尔/);
});
