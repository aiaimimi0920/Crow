import test from "node:test";
import assert from "node:assert/strict";
import { nativeRequest, checkHandshake } from "./native.mjs";
import { HOST } from "./contract.mjs";

test("ping uses the exact native host and preserves its handshake", async () => {
  const response = { ok: true, host: HOST, version: "0.1.1", protocol: 1 };
  const actual = await nativeRequest(async (host, message) => {
    assert.equal(host, HOST);
    assert.deepEqual(message, { action: "ping" });
    return response;
  }, { action: "ping" });
  checkHandshake(actual);
});

test("transport, host response, and protocol failures remain distinct", async () => {
  await assert.rejects(nativeRequest(async () => { throw Error("Specified native messaging host not found."); }, {}), /native_not_found/);
  await assert.rejects(nativeRequest(async () => ({ ok: false, code: "edge_task_expired" }), {}), /edge_task_expired/);
  for (const response of [null, {}, { ok: "true" }]) {
    await assert.rejects(nativeRequest(async () => response, {}), /native_protocol_failed/);
  }
  for (const response of [{}, { host: HOST, version: "0.1.0", protocol: 1 }, { host: "other", version: "0.1.1", protocol: 1 }]) {
    assert.throws(() => checkHandshake(response), /native_version_mismatch/);
  }
});
