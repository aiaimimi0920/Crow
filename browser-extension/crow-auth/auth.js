import { ORIGINS, targetIdentity, selectCookies, messages } from "./contract.mjs";
import { nativeRequest, checkHandshake } from "./native.mjs";

const status = document.getElementById("status");
const open = document.getElementById("open");
const submit = document.getElementById("submit");
const check = document.getElementById("check");
document.getElementById("identity").textContent = `扩展 ${chrome.runtime.getManifest().version} · ${chrome.runtime.id}`;
let task = null;
let tabId = null;
let busy = false;

async function profileId() {
  const saved = await chrome.storage.local.get("profileId");
  if (saved.profileId) return saved.profileId;
  const id = crypto.randomUUID().replaceAll("-", "");
  await chrome.storage.local.set({ profileId: id });
  return id;
}

async function native(message) {
  return nativeRequest((host, payload) => chrome.runtime.sendNativeMessage(host, payload),
    { ...message, profile_id: await profileId() });
}

async function run(operation) {
  if (busy) return;
  busy = true; check.disabled = true; open.disabled = true; submit.disabled = true;
  status.textContent = "正在连接本机助手…";
  try { await operation(); }
  catch (error) {
    status.textContent = (Object.hasOwn(messages, error.message) ? messages[error.message] : null) || (error.message === "native_unavailable"
      ? "未连接到本机 Crow 认证助手，请检查组件安装。"
      : "未提交认证会话。请重新连接 Crow 并检查目标页面。");
  } finally { busy = false; check.disabled = false; open.disabled = false; submit.disabled = !task || tabId === null; }
}

// Restore state before registering actions so a late read cannot replace a new claim.
const saved = await chrome.storage.session.get(["task", "tabId"]);
if (saved.task && saved.task.expires * 1000 > Date.now() && Number.isInteger(saved.tabId)) {
  task = saved.task; tabId = saved.tabId; submit.disabled = false;
  status.textContent = "认证任务已连接。完成后点击提交。";
}

check.addEventListener("click", () => run(async () => {
  const response = await native({ action: "ping" });
  checkHandshake(response);
  status.textContent = "本机助手 0.1.1 已连接。此检查未读取 Cookie，也未领取认证任务。";
}));

open.addEventListener("click", () => run(async () => {
  task = null; tabId = null;
  await chrome.storage.session.remove(["task", "tabId"]);
  task = await native({ action: "claim" });
  targetIdentity(task.target_url);
  const tab = await chrome.tabs.create({ url: task.target_url, active: false });
  tabId = tab.id;
  await chrome.storage.session.set({ task, tabId });
  status.textContent = "请在目标页面手动认证，然后回到本扩展提交。";
  await chrome.tabs.update(tabId, { active: true });
}));

submit.addEventListener("click", () => run(async () => {
  const tab = await chrome.tabs.get(tabId);
  if (tab.incognito || targetIdentity(tab.url) !== targetIdentity(task.target_url)) throw new Error("challenge_page_not_ready");
  // Explicit button only. There is no background worker, cookie listener or page injection.
  const stores = await chrome.cookies.getAllCookieStores();
  const store = stores.find((entry) => entry.tabIds.includes(tabId));
  if (!store) throw new Error("invalid_snapshot");
  const groups = await Promise.all(ORIGINS.map((url) => chrome.cookies.getAll({ domain: new URL(url).hostname, storeId: store.id })));
  groups.push(await chrome.cookies.getAll({ domain: "taobao.com", storeId: store.id }));
  const cookies = selectCookies(groups);
  await native({ action: "submit", request_id: task.request_id, nonce: task.nonce,
    tab_url: tab.url, cookies, user_agent: navigator.userAgent });
  await chrome.storage.session.remove(["task", "tabId"]);
  task = null; tabId = null;
  status.textContent = "已提交。请回 Crow 点击“已完成挑战”，等待 PC2 验证；提交不代表采集已恢复。";
}));

