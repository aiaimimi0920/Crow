import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { HOST } from "./contract.mjs";

test("manifest keeps the installed extension identity and minimal permissions", async () => {
  const manifest = JSON.parse(await readFile(new URL("./manifest.json", import.meta.url)));
  const id = [...createHash("sha256").update(Buffer.from(manifest.key, "base64")).digest("hex").slice(0, 32)]
    .map(c => String.fromCharCode(97 + parseInt(c, 16))).join("");
  assert.equal(id, "hkpcgieobdbcophagofgeglpiofmedhg");
  assert.equal(manifest.version, "0.1.1");
  assert.deepEqual(manifest.permissions, ["cookies", "nativeMessaging", "storage"]);
  assert.equal(manifest.background, undefined);
});

test("connection check reads no cookies; failed reconnect disables stale submission", async () => {
  const previous = { document: globalThis.document, chrome: globalThis.chrome };
  const elements = new Map();
  for (const id of ["status", "open", "submit", "check", "identity"]) {
    elements.set(id, { textContent: "", disabled: id === "submit", addEventListener(_, fn) { this.click = fn; } });
  }
  let cookieReads = 0;
  let tabCreates = 0;
  const removed = [];
  globalThis.document = { getElementById: id => elements.get(id) };
  globalThis.chrome = {
    runtime: {
      id: "hkpcgieobdbcophagofgeglpiofmedhg", getManifest: () => ({ version: "0.1.1" }),
      sendNativeMessage: async (host, message) => {
        assert.equal(host, HOST);
        if (message.action === "ping") return { ok: true, host: HOST, version: "0.1.1", protocol: 1 };
        throw Error("Specified native messaging host not found.");
      },
    },
    storage: {
      local: { get: async () => ({ profileId: "a".repeat(32) }) },
      session: {
        get: async () => ({ task: { expires: Date.now() / 1000 + 600 }, tabId: 7 }),
        remove: async keys => removed.push(keys),
      },
    },
    cookies: { getAll: async () => { cookieReads++; return []; } },
    tabs: { create: async () => { tabCreates++; return { id: 8 }; } },
  };
  try {
    let source = await readFile(new URL("./auth.js", import.meta.url), "utf8");
    for (const name of ["contract.mjs", "native.mjs"]) source = source.replace(`"./${name}"`, JSON.stringify(new URL(name, import.meta.url).href));
    await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
    assert.equal(elements.get("submit").disabled, false);
    await elements.get("check").click();
    assert.match(elements.get("status").textContent, /0\.1\.1 已连接/);
    assert.equal(cookieReads, 0);
    assert.equal(tabCreates, 0);
    assert.equal(removed.length, 0);
    await elements.get("open").click();
    assert.match(elements.get("status").textContent, /native_not_found/);
    assert.equal(elements.get("submit").disabled, true);
    assert.deepEqual(removed, [["task", "tabId"]]);
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete globalThis[name]; else globalThis[name] = value;
    }
  }
});
