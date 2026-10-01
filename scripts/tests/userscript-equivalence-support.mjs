import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { loadUserscriptParts, PART_RELATIVE_PATHS } from "../build-userscript.mjs";

const REFACTOR_COMMIT = "9f700178bd1ed19ac64db739a498baac0ea4b42c";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
let reviewedParts;

function historicalRefactorParts() {
  if (!reviewedParts) reviewedParts = PART_RELATIVE_PATHS.map((partPath) => {
    // CI already uses a full checkout for the repository's pinned integrity
    // baseline. Read only immutable reviewed Git objects, never the network.
    const source = execFileSync("git", ["--no-pager", "show", `${REFACTOR_COMMIT}:${partPath}`],
      { cwd: root, encoding: "utf8" }).replace(/\r\n?/g, "\n");
    const opening = `function crowSource_${path.basename(partPath, ".js")}() {\n`;
    const start = source.indexOf(opening);
    if (start < 0 || !source.endsWith("\n}\n")) throw new Error("Invalid reviewed source unit");
    return { metadata: source.slice(0, start), body: source.slice(start + opening.length, -2) };
  });
  return reviewedParts;
}

export function restoreReviewedSource() {
  // This certificate remains pinned to the reviewed syntax refactor. Later
  // intentional security fixes have their own behavior regressions.
  const parts = historicalRefactorParts();
  const legacyNames = (text) => text.replaceAll("getCleanDetailContext", "getCleanContext")
    .replaceAll("extractDetailPageData", "extractPageData");
  const restoredHelpers = legacyNames(parts[8].body).split(/(?<=\n)/)
    .map((line) => line === "\n" || line === "" ? line : "    " + line).join("")
    .replace(/[ \t]+$/gm, "");
  const restoredPanel = legacyNames(parts[9].body).replace(
    "        // --- Data Loading ---", restoredHelpers + "        // --- Data Loading ---",
  );
  return parts[0].metadata + "(function() {\n" + parts.slice(0, 8).map((part) => part.body).join("") +
    restoredPanel + parts.slice(10).map((part) => part.body).join("") + "})();\n";
}

export function extractFixture(fixture, legacy = false) {
  let source = loadUserscriptParts()[8].body;
  if (legacy) {
    // Execute the hash-verified historical nested helper in its original panel
    // scope. Instrument only its return boundary to capture the private reader.
    const reviewed = restoreReviewedSource();
    const init = reviewed.slice(reviewed.indexOf("    function initHelper()"),
      reviewed.indexOf("    // --- Main Entry ---")).trimEnd();
    source = init.slice(0, -1) + "globalThis.historicalExtract = extractPageData;\n}";
  }
  const nodes = fixture.nodes || {};
  const document = {
    title: fixture.title || "测试房源",
    body: { innerText: fixture.body || "" },
    querySelector: (selector) => nodes[selector] || null,
    getElementById: () => null,
    querySelectorAll: (selector) => selector === "script.J_COMPONENT" ?
      (fixture.scripts || []).map((textContent) => ({ textContent })) : (fixture.stats || []),
  };
  const context = { document, window: { location: new URL(fixture.url), scrollTo() {} },
    formatLocalDateTime: (value) => new Date(value).toISOString(),
    console: { warn() {} }, URLSearchParams, isDetail: true,
    GM_getValue: (_key, fallback) => fallback, log() {}, setTimeout() {},
  };
  const extract = vm.runInNewContext(source +
    (legacy ? ";initHelper();globalThis.historicalExtract" : ";extractDetailPageData"), context);
  return { document, window: context.window, extract: () => JSON.parse(JSON.stringify(extract())) };
}

export function dispatchFixture(source, url, { name = "", values = {} } = {}) {
  const events = [], logs = [], timers = [], scrolls = [], requests = [];
  let timerId = 0;
  const location = new URL(url);
  const window = { location, name, addEventListener: (event, callback) => events.push([event, callback.name]),
    scrollTo: (value) => scrolls.push(value), close() { events.push(["close"]); },
  };
  const document = {
    title: "fixture", body: { innerHTML: "", innerText: "", scrollHeight: 800, appendChild() {} },
    head: { appendChild: (node) => events.push(["head", node.textContent || node.innerHTML || ""]) },
    documentElement: {}, querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
    createElement: () => ({ style: {}, appendChild() {}, addEventListener() {}, setAttribute() {} }),
  };
  class FixedDate extends Date {
    constructor(...args) { super(...(args.length ? args : [1790812800000])); }
    static now() { return 1790812800000; }
  }
  const math = Object.create(Math);
  math.random = () => 0.25;
  const context = {
    window, document, URL, URLSearchParams, Date: FixedDate, Math: math,
    crypto: { getRandomValues: (bytes) => bytes.fill(1) },
    console: { log: (...args) => logs.push(args), warn: (...args) => logs.push(args), error: (...args) => logs.push(args) },
    sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    GM_info: { version: "5.5.0", scriptHandler: "Tampermonkey" },
    GM_getValue: (key, fallback) => Object.hasOwn(values, key) ? values[key] : fallback,
    GM_setValue: (key, value) => { values[key] = value; },
    GM_deleteValue: (key) => { delete values[key]; },
    GM_listValues: () => Object.keys(values),
    GM_registerMenuCommand: (label) => events.push(["menu", label]),
    GM_addValueChangeListener: (key) => events.push(["valueListener", key]),
    GM_xmlhttpRequest: (request) => { requests.push(request.url); return { abort() {} }; },
    GM_openInTab: (target) => events.push(["open", target]),
    setTimeout: (callback, delay) => { timers.push(["timeout", delay, callback.name]); return ++timerId; },
    setInterval: (callback, delay) => { timers.push(["interval", delay, callback.name]); return ++timerId; },
    clearTimeout() {}, clearInterval() {},
    MutationObserver: class { observe() {} disconnect() {} },
  };
  vm.runInNewContext(source, context, { timeout: 1000 });
  return JSON.parse(JSON.stringify({ events, logs, timers, scrolls, requests, values,
    windowName: window.name, title: document.title, body: document.body.innerHTML,
    captchaMonitor: Boolean(window.captcha_monitor_active),
  }));
}
