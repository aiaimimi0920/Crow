import { element } from "./desktop_dom.ts";
import { renderOperations, renderReceipt, operationsFreshness } from "./desktop_operations_view.ts";
import { object } from "./desktop_value.ts";

let snapshot: unknown = null;
let receivedAt = 0;
let failed = false;
const render = () => {
  const table = document.getElementById("operationsQueue");
  const focused = Boolean(table && table === document.activeElement);
  const left = table?.scrollLeft || 0;
  element("operationsSnapshot").innerHTML = renderOperations(snapshot, receivedAt, failed);
  const updated = document.getElementById("operationsQueue");
  if (updated) { updated.scrollLeft = left; if (focused) updated.focus({ preventScroll: true }); }
};

export const operationsTemplate = `<section id="operationsPage" class="ops-page hidden" aria-labelledby="operationsTitle">
  <div class="workspace-heading"><div><h1 id="operationsTitle" tabindex="-1">运维观察台</h1><p class="status-line">定位积压、认证阻塞与控制结果 · 刷新不触发 solver 或模型探测</p></div><button id="operationsRefresh" class="primary-button">刷新状态</button></div>
  <section class="ops-section"><h2>运行控制</h2><div class="ops-actions">
    <button id="operationsPause" disabled>等待运行状态</button><button id="operationsSeedAuth">链接认证</button><button id="operationsDetailAuth">详情认证</button>
    <button id="operationsRestart" class="danger-button" disabled>重启 PC2 采集</button></div><p id="operationsRestartStatus" class="status-line" role="status">尚未读取控制器状态</p>
    <p class="status-line">开始采集只取消操作员暂停，不绕过认证；重启需确认且保留数据库和认证浏览器。请求提交不等于执行成功。</p>
    <details><summary>最近重启回执</summary><div id="operationsRestartReceipt">尚未读取</div></details></section>
  <div id="operationsSnapshot"><div class="empty-state">正在读取运行状态...</div></div>
  <section class="ops-section"><h2>生效配置与参数控制</h2><div class="ops-actions"><button id="operationsConfigRefresh">读取生效配置 / 回执</button>
    <button data-settings-target="setting-workers.links">调整 Worker 并发</button><button data-settings-target="setting-intervals.links">调整间隔 / 重试</button><button data-settings-target="setting-ai.allow_gpt">GPT 开关 / AI 模型</button></div>
    <p id="operationsConfigStatus" class="status-line" role="status">尚未读取受保护配置；请使用已安装安全组件或在设置中填写控制授权。</p>
    <div id="operationsConfig"></div><p class="status-line">参数编辑沿用版本校验、二次确认与应用回执；不会从本页绕过授权或立即改写生产配置。</p></section>
</section>`;

export function publishOperations(value: unknown): void {
  snapshot = value; receivedAt = Date.now(); failed = false; render();
  element("operationsRestartReceipt").innerHTML = renderReceipt(object(object(value).engine_restart).request);
}
export function failOperations(): void { failed = true; render(); }
export function resetOperations(): void {
  snapshot = null; receivedAt = 0; failed = false; render();
  element("operationsRestartReceipt").textContent = "尚未读取";
  element<HTMLButtonElement>("operationsPause").disabled = true;
  element<HTMLButtonElement>("operationsRestart").disabled = true;
  element("operationsRestartStatus").textContent = "尚未读取控制器状态";
}
export function initializeOperations(actions: { refresh: () => Promise<void>; pause: () => Promise<void>; restart: () => Promise<void>; auth: (scope: "seed" | "detail") => unknown }): void {
  element("operationsRefresh").addEventListener("click", () => void actions.refresh());
  element("operationsPause").addEventListener("click", () => void actions.pause());
  element("operationsRestart").addEventListener("click", () => void actions.restart());
  element("operationsSeedAuth").addEventListener("click", () => actions.auth("seed"));
  element("operationsDetailAuth").addEventListener("click", () => actions.auth("detail"));
  setInterval(() => {
    const node = document.getElementById("operationsFreshness");
    if (!node || !snapshot) return;
    const freshness = operationsFreshness(snapshot, receivedAt, failed);
    node.textContent = freshness.text;
    node.classList.toggle("warn", freshness.warning); node.classList.toggle("ok", !freshness.warning);
  }, 5000);
}
