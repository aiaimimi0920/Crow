import { callAction } from "./desktop_actions.ts";
import { state } from "./desktop_state.ts";
import { parseEditableValue } from "./desktop_edit_value.ts";
import { escapeHtml as esc } from "./desktop_dom.ts";
import {
  $,
  fmt,
  getJson,
  postJson,
  setDetailActionStatus,
  setDetailBusy,
  statusClass,
} from "./desktop_shared.ts";
import { collectionStatusLabel, itemRegion } from "./desktop_regions.ts";
import standardizedFields from "./desktop_standardized_fields.json";
import { renderOverview } from "./desktop_overview.ts";
import { updateRuntimeControls, refreshEngineRestartStatus } from "./desktop_runtime_controls.ts";
import { errorMessage, object, safeExternalUrl } from "./desktop_value.ts";
import { recordArray, type CollectionRecord } from "./desktop_collection_contract.ts";
import { DETAIL_PREVIEW_MAX_CHARS } from "./desktop_config.ts";
import { authTargetScope } from "./desktop_auth_target.ts";

export function hideDetailPanel() {
  state.detailRequestId += 1;
  setDetailActionStatus("");
  $("refresh").classList.add("primary-button");
  state.selectedItemId = null;
  document.querySelectorAll("tr.item-row.selected").forEach((row) => row.classList.remove("selected"));
  $("detailPanel").classList.add("hidden");
  $("contentLayout").classList.add("detail-hidden");
  $("detailTitle").textContent = "已采集 HTML 文本";
  $("detailHint").textContent = "商品详情页采集完成后保存的 HTML/文本内容，用于后续 AI 分析。";
  $("analysisActions").classList.add("hidden");
  $("editButton").textContent = "手动编辑";
  $("manualUpdateButton").classList.add("hidden");
  $("analysisAttemptCount").textContent = "AI 分析次数：-";
  $("detailPath").textContent = "";
  $("detailHtmlText").textContent = "点击“商品详情页采集”中的任一商品查看。";
  $("detailHtmlText").classList.remove("hidden");
  $("standardizedRows").classList.add("hidden");
  $("standardizedRows").innerHTML = "";
  state.selectedAnalysisItemId = null;
  state.selectedAnalysisRecord = null;
  state.editingAnalysis = false;
}

export function showDetailPanel() {
  $("detailPanel").classList.remove("hidden");
  $("contentLayout").classList.remove("detail-hidden");
}

export const STANDARDIZED_FIELD_LABELS = standardizedFields as [string, string[]][];

export function isMeaningfulValue(value: unknown): boolean {
  if (value === null || value === undefined) {
    return false;
  }
  if (typeof value === "string") {
    return value.trim() !== "";
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  if (typeof value === "object") {
    return Object.keys(value).length > 0;
  }
  return true;
}

export function displayValue(value: unknown): string {
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  if (typeof value === "object" && value !== null) {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

export { parseEditableValue };

export function firstExistingValue(record: CollectionRecord, keys: readonly string[]): unknown {
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(record, key) && isMeaningfulValue(record[key])) {
      return record[key];
    }
  }
  return undefined;
}

export function editableKeyFor(keys: readonly string[]): string {
  return keys.find((key) => /^[a-z_][a-z0-9_]*$/i.test(key)) || keys[0];
}

export function renderStandardizedEntries(record: CollectionRecord | null, editable = false): string {
  const source = record || {};
  const usedKeys = new Set<string>();
  const rows: [string, string, unknown][] = [];

  for (const [label, keys] of STANDARDIZED_FIELD_LABELS) {
    const value = firstExistingValue(source, keys);
    keys.forEach((key) => usedKeys.add(key));
    if (isMeaningfulValue(value)) {
      rows.push([label, editableKeyFor(keys), value]);
    }
  }

  Object.entries(source)
    .filter(([key, value]) => !usedKeys.has(key) && !key.startsWith("_") && isMeaningfulValue(value))
    .forEach(([key, value]) => rows.push([key, key, value]));

  if (rows.length === 0) {
    return '<p class="status-line">没有可展示的 AI 标准化数据。</p>';
  }

  return `<table class="standardized-table">
    <thead><tr><th>条目名称</th><th>数值内容</th></tr></thead>
    <tbody>${rows
      .map(([label, key, value]) => {
        const renderedValue = displayValue(value);
        const valueControl = editable
          ? `<textarea class="editable-field" data-field="${esc(key)}" data-value-type="${typeof value}">${esc(renderedValue)}</textarea>`
          : `<pre class="value-cell">${esc(renderedValue)}</pre>`;
        return `<tr><td>${fmt(label)}</td><td>${valueControl}</td></tr>`;
      })
      .join("")}</tbody>
  </table>`;
}

export function analysisAttemptCount(data: CollectionRecord): number {
  const payload = object(object(data.item).source_payload);
  const attempts = Number(payload._analysis_attempt_count || 0);
  return Number.isFinite(attempts) ? attempts : 0;
}

export function runtimeStateFromOverview(data: CollectionRecord): string {
  if (typeof data.runtime_state === "string" && data.runtime_state.trim()) {
    return data.runtime_state;
  }
  const status = object(data.status);
  if (typeof status.runtime_state === "string" && status.runtime_state.trim()) {
    return status.runtime_state;
  }
  const solver = object(status.captcha_solver);
  const authRequired = Boolean(solver.manual_required || solver.force_unlock_flag_exists);
  if (authRequired) {
    const lastRequest = object(solver.last_request);
    const targetUrl = String(lastRequest.target_url || lastRequest.url || "").toLowerCase();
    const detailOnlyAuth = authTargetScope(targetUrl) === "detail";
    const seedStageCanContinue =
      Number(status.seed_scan_job_pending || 0) > 0 ||
      Number(status.seed_scan_job_in_progress || 0) > 0 ||
      Number(status.seed_scan_progress_pending || 0) > 0 ||
      Number(status.seed_scan_progress_in_progress || 0) > 0;
    if (detailOnlyAuth && seedStageCanContinue) {
      return "运行中";
    }
    return "待认证";
  }
  if (status.paused) {
    return "暂停中";
  }
  const modules = object(data.modules);
  const links = object(modules.links);
  const details = object(modules.details);
  const analysis = object(modules.analysis);
  const hasItems = Number(links.unique_items || 0) > 0;
  const detailOpen =
    Number(details.pending || 0) + Number(details.failed || 0) + Number(details.blocked || 0);
  const analysisOpen =
    Number(analysis.ready || 0) +
    Number(analysis.pending || 0) +
    Number(analysis.failed || 0) +
    Number(analysis.blocked || 0);
  if (hasItems && detailOpen === 0 && analysisOpen === 0) {
    return "已完成";
  }
  return "运行中";
}

export async function loadOverview() {
  const requestId = ++state.overviewRequestId;
  const apiBase = state.apiBase;
  const data = await getJson("/api/collection/overview");
  if (requestId !== state.overviewRequestId || apiBase !== state.apiBase) return false;
  state.lastOverview = data;
  const runtimeState = runtimeStateFromOverview(data);
  $("cards").innerHTML = renderOverview(data, runtimeState);
  $("runtimePauseButton").addEventListener("click", () => callAction("toggleRuntimePause"));
  $("engineRestartButton").addEventListener("click", () => callAction("requestEngineRestart"));
  for (const scope of ["seed", "detail"] as const) {
    $(`${scope}AuthButton`).addEventListener("click", () => callAction("openAuthChallenge", scope));
  }
  updateRuntimeControls();
  void refreshEngineRestartStatus();
  $("connectionStatus").textContent = `已连接 ${state.apiBase}`;
  $("overviewNotice").classList.add("hidden");
  return true;
}

export function renderItems(data: CollectionRecord): void {
  state.total = Number(data.total) || 0;
  const first = state.total ? state.offset + 1 : 0;
  $("listStatus").textContent = `共 ${state.total} 项 · 当前 ${first}-${Math.min(state.offset + state.limit, state.total)}`;
  $<HTMLButtonElement>("prev").disabled = state.offset === 0;
  $<HTMLButtonElement>("next").disabled = state.offset + state.limit >= state.total;
  if (state.stage !== "details" && state.stage !== "analysis") {
    $("detailPanel").classList.add("hidden");
    $("contentLayout").classList.add("detail-hidden");
  }
  $("items").innerHTML = recordArray(data.items)
    .map((item) => {
      const currentStatus = collectionStatusLabel(item);
      const selected = String(item.item_id) === state.selectedItemId ? " selected" : "";
      return `<tr class="item-row${selected}" data-id="${esc(item.item_id)}" tabindex="0" aria-label="商品 ${esc(item.item_id)}">
        <td><strong>${fmt(item.item_id)}</strong></td>
        <td><a href="${esc(safeExternalUrl(item.source_url))}" target="_blank" rel="noopener noreferrer">${fmt(item.source_url)}</a></td>
        <td>${fmt(itemRegion(item))}</td>
        <td><span class="pill ${statusClass(currentStatus)}">${fmt(currentStatus)}</span></td>
      </tr>`;
    })
    .join("") || '<tr><td colspan="4" class="empty-state">当前阶段和地区没有商品。<br>可调整地区筛选或刷新数据。</td></tr>';
  document.querySelectorAll<HTMLTableRowElement>("tr.item-row").forEach((row) => {
    const open = () => {
      if (!row.dataset.id) return;
      if (state.stage === "details") {
        loadDetailHtml(row.dataset.id);
      } else if (state.stage === "analysis") {
        loadAnalysisData(row.dataset.id);
      }
    };
    row.addEventListener("click", (event) => {
      if (!(event.target instanceof Element && event.target.closest("a"))) open();
    });
    row.addEventListener("keydown", (event) => {
      if (event.target !== row || !["Enter", " "].includes(event.key)) return;
      event.preventDefault();
      open();
    });
  });
}

export async function loadItems() {
  const requestId = ++state.itemsRequestId;
  $("listStatus").textContent = "加载中...";
  $("items").setAttribute("aria-busy", "true");
  $<HTMLButtonElement>("prev").disabled = true;
  $<HTMLButtonElement>("next").disabled = true;
  const regionParam = state.selectedLocationCode ? `&location_code=${encodeURIComponent(state.selectedLocationCode)}` : "";
  try {
    const data = await getJson(`/api/collection/items?stage=${encodeURIComponent(state.stage)}&limit=${state.limit}&offset=${state.offset}${regionParam}`);
    if (requestId === state.itemsRequestId) renderItems(data);
  } catch (error) {
    if (requestId !== state.itemsRequestId) return;
    $("listStatus").textContent = `列表读取失败：${errorMessage(error)}`;
    $("items").innerHTML = '<tr><td colspan="4" class="empty-state error">无法读取商品列表，请检查 API 连接后重试。</td></tr>';
    throw error;
  } finally {
    if (requestId === state.itemsRequestId) $("items").setAttribute("aria-busy", "false");
  }
}

function selectItemRow(itemId: string): number {
  setDetailActionStatus("");
  $("refresh").classList.add("primary-button");
  state.selectedItemId = String(itemId);
  document.querySelectorAll<HTMLTableRowElement>("tr.item-row").forEach((row) => {
    row.classList.toggle("selected", row.dataset.id === state.selectedItemId);
  });
  return ++state.detailRequestId;
}

export async function loadDetailHtml(itemId: string): Promise<void> {
  if (state.stage !== "details") {
    return;
  }
  const requestId = selectItemRow(itemId);
  showDetailPanel();
  $("detailTitle").textContent = `已采集 HTML 文本 - ${itemId}`;
  $("detailHint").textContent = "商品详情页采集完成后保存的 HTML/文本内容，用于后续 AI 分析。";
  $("analysisActions").classList.add("hidden");
  $("detailPath").textContent = "加载中...";
  $("standardizedRows").classList.add("hidden");
  $("detailHtmlText").classList.remove("hidden");
  $("detailHtmlText").textContent = "正在读取已采集的详情页 HTML/文本...";

  try {
    const data = await getJson(`/api/collection/item?item_id=${encodeURIComponent(itemId)}&max_chars=${DETAIL_PREVIEW_MAX_CHARS}`);
    if (requestId !== state.detailRequestId || state.stage !== "details" || state.selectedItemId !== String(itemId)) return;
    const artifact = object(object(data.artifacts).detail_html);
    const content = typeof artifact.content === "string" ? artifact.content : (artifact.json ? JSON.stringify(artifact.json, null, 2) : "");
    $("detailPath").textContent = artifact.path ? String(artifact.path) : "未返回详情文件路径";
    $("detailHtmlText").textContent = content || "未找到已采集的 HTML 文本。";
  } catch (error) {
    if (requestId !== state.detailRequestId || state.stage !== "details" || state.selectedItemId !== String(itemId)) return;
    $("detailPath").textContent = "";
    $("detailHtmlText").textContent = `读取失败：${errorMessage(error)}`;
  }
}

export async function loadAnalysisData(itemId: string): Promise<void> {
  if (state.stage !== "analysis") {
    return;
  }
  const requestId = selectItemRow(itemId);
  setDetailBusy(true);
  showDetailPanel();
  state.selectedAnalysisItemId = itemId;
  state.selectedAnalysisRecord = null;
  state.editingAnalysis = false;
  $("detailTitle").textContent = `AI 标准化数据 - ${itemId}`;
  $("detailHint").textContent = "经过 AI 分析调整后的标准化数据；每一行是一个条目名称和对应的数值内容。";
  $("detailPath").textContent = "加载中...";
  $("analysisActions").classList.remove("hidden");
  $("editButton").textContent = "手动编辑";
  $("manualUpdateButton").classList.add("hidden");
  $("detailHtmlText").classList.add("hidden");
  $("standardizedRows").classList.remove("hidden");
  $("standardizedRows").innerHTML = '<p class="status-line">正在读取 AI 标准化数据...</p>';

  try {
    const data = await getJson(`/api/collection/item?item_id=${encodeURIComponent(itemId)}&max_chars=${DETAIL_PREVIEW_MAX_CHARS}`);
    if (requestId !== state.detailRequestId || state.stage !== "analysis" || state.selectedItemId !== String(itemId)) return;
    const finalArtifact = object(object(data.artifacts).final_json);
    const standardized = object(data.flat_item || finalArtifact.json);
    state.selectedAnalysisRecord = standardized;
    $("analysisAttemptCount").textContent = `AI 分析次数：${analysisAttemptCount(data)}`;
    $("detailPath").textContent = finalArtifact.path ? String(finalArtifact.path) : "标准化数据来自数据库字段";
    $("standardizedRows").innerHTML = renderStandardizedEntries(standardized);
  } catch (error) {
    if (requestId !== state.detailRequestId || state.stage !== "analysis" || state.selectedItemId !== String(itemId)) return;
    $("detailPath").textContent = "";
    $("standardizedRows").innerHTML = `<p class="error">读取失败：${esc(errorMessage(error))}</p>`;
  } finally {
    if (requestId === state.detailRequestId) setDetailBusy(false);
  }
}

export function startManualEdit() {
  if (!state.selectedAnalysisItemId || !state.selectedAnalysisRecord) {
    return;
  }
  state.editingAnalysis = true;
  $("refresh").classList.remove("primary-button");
  setDetailActionStatus("编辑尚未保存；手动更新后才会写入数据库。", "warn");
  $("editButton").textContent = "取消编辑";
  $("manualUpdateButton").classList.remove("hidden");
  $("standardizedRows").innerHTML = renderStandardizedEntries(state.selectedAnalysisRecord, true);
}

export async function cancelManualEdit() {
  if (!state.selectedAnalysisItemId) {
    return;
  }
  state.editingAnalysis = false;
  $("editButton").textContent = "手动编辑";
  $("manualUpdateButton").classList.add("hidden");
  await loadAnalysisData(state.selectedAnalysisItemId);
}

export async function submitManualUpdate() {
  if (!state.selectedAnalysisItemId || !state.editingAnalysis) {
    return;
  }
  const requestId = state.detailRequestId;
  const updates: CollectionRecord = {};
  try {
    document.querySelectorAll<HTMLTextAreaElement>(".editable-field").forEach((field) => {
      const key = field.dataset.field;
      if (key) updates[key] = parseEditableValue(field.value, field.dataset.valueType);
    });
  } catch (error) {
    setDetailActionStatus(error instanceof Error ? error.message : "字段值无效", "warn");
    return;
  }
  setDetailActionStatus("正在手动更新数据库...");
  const result = await postJson("/api/collection/item/manual_update", {
    item_id: state.selectedAnalysisItemId,
    updates,
  });
  if (requestId !== state.detailRequestId) return;
  state.selectedAnalysisRecord = object(result.flat_item || updates);
  state.editingAnalysis = false;
  $("editButton").textContent = "手动编辑";
  $("manualUpdateButton").classList.add("hidden");
  $("refresh").classList.add("primary-button");
  setDetailActionStatus(`手动更新完成：${Array.isArray(result.updated_fields) ? result.updated_fields.length : 0} 个字段`, "ok");
  $("standardizedRows").innerHTML = renderStandardizedEntries(state.selectedAnalysisRecord);
  await callAction("reloadAfterDetailAction", { requestId });
}

export async function requestReanalysis() {
  if (!state.selectedAnalysisItemId) {
    return;
  }
  const requestId = state.detailRequestId;
  setDetailActionStatus("正在提交 AI 再分析请求...");
  const result = await postJson("/api/collection/item/reanalyze", {
    item_id: state.selectedAnalysisItemId,
    reason: "operator_requested",
  });
  if (requestId !== state.detailRequestId) return;
  setDetailActionStatus(`已加入 AI 再分析队列；当前分析次数：${result.analysis_attempt_count}`, "ok");
  await callAction("reloadAfterDetailAction", { requestId, includeOverview: true });
}
