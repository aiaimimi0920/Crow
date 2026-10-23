import { installedControlOrigin, installedRestartRequest, installedRuntimeRequest } from "./desktop_settings_transport.ts";
import { controlOrigin } from "./desktop_settings_contract.ts";
import { object } from "./desktop_value.ts";
import { element } from "./desktop_dom.ts";
import { fetchWithTimeout } from "./desktop_http.ts";
import { AUTO_REFRESH_INTERVAL_MS, CONTROL_ORIGIN_CACHE_MS, RESTART_POLL_INTERVAL_MS, RUNTIME_TIMEOUT_MS } from "./desktop_config.ts";
import { renderReceipt } from "./desktop_operations_view.ts";

type Controls = {
  apiBase: () => string;
  reload: () => Promise<void>;
  showDialog: (dialog: HTMLDialogElement) => void;
};
let controls: Controls;
let busy = false;
let retryRequest: { base: string; id: string } | null = null;
let installedOrigin: string | null = null;
let statusBusy = false;
let statusTimer: ReturnType<typeof setTimeout> | undefined;
let statusBase = "";
let nextStatusAt = 0;
let originExpiresAt = 0;

function notice(message: string): void {
  const node = element("overviewNotice");
  node.textContent = message;
  node.classList.remove("hidden");
}

export function updateRuntimeControls(): void {
  const token = element<HTMLInputElement>("restartToken").value.trim();
  const button = document.getElementById("engineRestartButton") as HTMLButtonElement | null;
  if (button) button.disabled = busy || button.dataset.available !== "true" || !(installedOrigin || token);
  const toggle = document.getElementById("runtimePauseButton") as HTMLButtonElement | null;
  if (toggle) toggle.disabled = busy;
  const opsPause = document.getElementById("operationsPause") as HTMLButtonElement | null;
  if (opsPause) { opsPause.disabled = !toggle || toggle.disabled; opsPause.textContent = toggle?.textContent || "等待运行状态"; }
  const opsRestart = document.getElementById("operationsRestart") as HTMLButtonElement | null;
  if (opsRestart) opsRestart.disabled = !button || button.disabled;
  const opsHint = document.getElementById("operationsRestartStatus");
  if (opsHint) opsHint.textContent = document.getElementById("engineRestartStatus")?.textContent || "尚未读取控制器状态";
}

export function initializeRuntimeControls(options: Controls): void {
  controls = options;
  element("restartToken").addEventListener("input", updateRuntimeControls);
}

export async function refreshEngineRestartStatus(force = false): Promise<void> {
  if (statusBusy || !document.getElementById("engineRestartButton")) return;
  const base = controls.apiBase();
  if (!force && base === statusBase && Date.now() < nextStatusAt) return;
  if (base !== statusBase) { installedOrigin = null; originExpiresAt = 0; }
  statusBase = base;
  statusBusy = true;
  let delay = AUTO_REFRESH_INTERVAL_MS;
  try {
    if (Date.now() >= originExpiresAt) {
      installedOrigin = await installedControlOrigin();
      originExpiresAt = Date.now() + CONTROL_ORIGIN_CACHE_MS;
    }
    if (!installedOrigin) return;
    const status = await installedRestartRequest(installedOrigin);
    if (base !== controls.apiBase()) return;
    const request = object(status.request);
    const receipt = document.getElementById("operationsRestartReceipt");
    if (receipt) receipt.innerHTML = renderReceipt(request);
    if (["requested", "restarting"].includes(String(request.status))) delay = RESTART_POLL_INTERVAL_MS;
    const labels: Record<string, string> = {
      requested: "等待 PC2 接收", restarting: "PC2 正在重启", succeeded: "PC2 采集 Worker 已重启",
      failed: "重启失败，请检查 PC2", expired: "重启请求已过期", unknown: "重启结果未确认，请检查 PC2",
    };
    const blocked = ["requested", "restarting", "unknown"].includes(String(request.status));
    const button = document.getElementById("engineRestartButton") as HTMLButtonElement | null;
    if (button) button.dataset.available = String(status.available === true && !blocked);
    const hint = document.getElementById("engineRestartStatus");
    if (hint) hint.textContent = labels[String(request.status)] || (status.available ? "PC2 控制器已连接" : "PC2 控制器未连接");
  } catch {
    if (base !== controls.apiBase()) return;
    installedOrigin = null;
    originExpiresAt = 0;
    const button = document.getElementById("engineRestartButton") as HTMLButtonElement | null;
    if (button) button.dataset.available = "false";
    const hint = document.getElementById("engineRestartStatus");
    if (hint) hint.textContent = "安全重启通道暂不可用，正在重新连接";
  } finally {
    statusBusy = false;
    updateRuntimeControls();
    clearTimeout(statusTimer);
    nextStatusAt = Date.now() + delay;
    statusTimer = setTimeout(() => void refreshEngineRestartStatus(), delay);
  }
}

async function post(base: string, action: string, payload: object, token = ""): Promise<Record<string, unknown>> {
  base = controlOrigin(base);
  if (!token) throw new Error("Control authorization is required");
  const headers = { "Content-Type": "application/json", "X-FAPAI-Control-Token": token };
  const response = await fetchWithTimeout(`${base.replace(/\/$/, "")}/api/collection/control/${action}`, {
    method: "POST", headers, body: JSON.stringify(payload), redirect: "error",
  }, RUNTIME_TIMEOUT_MS);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const record = object(await response.json());
  if (record.ok === false) throw new Error(String(record.message || record.error || `HTTP ${response.status}`));
  return record;
}

export async function toggleRuntimePause(): Promise<void> {
  if (busy) return;
  const action = element<HTMLButtonElement>("runtimePauseButton").dataset.action || "pause";
  const base = controls.apiBase();
  busy = true;
  updateRuntimeControls();
  try {
    if (!["start", "pause", "resume"].includes(action)) throw new Error("Unsupported runtime action");
    const origin = await installedControlOrigin();
    if (origin) await installedRuntimeRequest(origin, action);
    else await post(base, action, {}, element<HTMLInputElement>("restartToken").value.trim());
    if (base === controls.apiBase()) await controls.reload();
  } catch (error) {
    if (base === controls.apiBase()) notice(`切换运行状态失败：${error instanceof Error ? error.message : String(error)}`);
  }
  finally { busy = false; updateRuntimeControls(); }
}

export async function requestEngineRestart(): Promise<void> {
  if (busy || element<HTMLButtonElement>("engineRestartButton").disabled) return;
  const trigger = document.activeElement;
  const base = controls.apiBase();
  const token = element<HTMLInputElement>("restartToken").value.trim();
  const origin = installedOrigin;
  const dialog = element<HTMLDialogElement>("engineRestartDialog");
  busy = true;
  updateRuntimeControls();
  dialog.returnValue = "cancel";
  const decision = new Promise<string>((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue), { once: true }));
  controls.showDialog(dialog);
  try {
    if (await decision !== "confirm" || base !== controls.apiBase()) return;
    retryRequest = retryRequest?.base === base ? retryRequest : { base, id: crypto.randomUUID() };
    const result = origin
      ? await installedRestartRequest(origin, retryRequest.id)
      : await post(base, "restart", { request_id: retryRequest.id }, token);
    retryRequest = null;
    if (base !== controls.apiBase()) return;
    await controls.reload();
    await refreshEngineRestartStatus(true);
    notice(result.warning ? String(result.warning) : "重启请求已提交 NAS，执行结果以状态栏中的 PC2 回执为准；提交不代表重启完成。");
  } catch (error) {
    if (base === controls.apiBase()) notice(`重启请求未确认：${error instanceof Error ? error.message : String(error)}。请先刷新状态；重试会复用请求编号。`);
    await refreshEngineRestartStatus(true);
  } finally {
    busy = false;
    updateRuntimeControls();
    const restart = document.getElementById("engineRestartButton") as HTMLButtonElement | null;
    if (base === controls.apiBase()) {
      if (trigger instanceof HTMLButtonElement && trigger.isConnected && !trigger.disabled && trigger.getClientRects().length) trigger.focus();
      else if (!element("operationsPage").classList.contains("hidden")) element("operationsPause").focus();
      else (restart?.disabled ? document.getElementById("runtimePauseButton") : restart)?.focus();
    }
  }
}
