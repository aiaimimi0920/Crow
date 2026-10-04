import "./styles.css";
import { registerActions } from "./desktop_actions.ts";
import { AUTO_REFRESH_INTERVAL_MS, REGION_REFRESH_INTERVAL_MS } from "./desktop_config.ts";
import { isCollectionStage, type RefreshOptions } from "./desktop_collection_contract.ts";
import { errorMessage } from "./desktop_value.ts";
import {
  defaultBrowserApiBase,
  state,
} from "./desktop_state.ts";
import { startupApiBase, CONFIGURATION_ERROR } from "./desktop_startup_config.ts";
import { isConfigurationBlocked, setConfigurationBlocked } from "./desktop_http.ts";
import { tryInvoke } from "./desktop_native.ts";
import { mountTemplate } from "./desktop_template.ts";
import { initializeShell } from "./desktop_shell.ts";
import { $, formatRefreshTime, setAutoRefreshStatus, setDetailActionStatus, setDetailBusy, showManagedDialog } from "./desktop_shared.ts";
import { escapeHtml as esc } from "./desktop_dom.ts";
import { hideDetailPanel, loadItems, loadOverview, requestReanalysis, startManualEdit, cancelManualEdit, submitManualUpdate } from "./desktop_collection_views.ts";
import { loadRegions, resetSelectedRegionLinks } from "./desktop_regions.ts";
import { resetAuthChallenge, openAuthChallenge, reloadAuthChallenge, resumeAfterAuthChallenge } from "./desktop_auth.ts";
import { initializeRuntimeControls, toggleRuntimePause, requestEngineRestart } from "./desktop_runtime_controls.ts";
import { resetOverviewHistory } from "./desktop_overview.ts";
import { initializeSettings } from "./desktop_settings.ts";

mountTemplate();
const resetRuntimeSettings = initializeSettings(() => state.apiBase, showManagedDialog);
initializeShell(reloadAll);
initializeRuntimeControls({ apiBase: () => state.apiBase, reload: reloadAll, showDialog: showManagedDialog });
$("toggleRegions").addEventListener("click", () => {
  const collapsed = $("regionFilters").classList.toggle("hidden");
  $("toggleRegions").setAttribute("aria-expanded", String(!collapsed));
  $("toggleRegions").textContent = collapsed ? "筛选地区" : "收起筛选";
});

export async function reloadAll(options: RefreshOptions = {}): Promise<void> {
  const silent = Boolean(options && options.silent);
  if (state.refreshInFlight) {
    if (!silent) {
      setAutoRefreshStatus("刷新已在进行中");
    }
    return;
  }
  state.refreshInFlight = true;
  const requestId = ++state.refreshRequestId;
  const apiBase = state.apiBase;
  const current = () => requestId === state.refreshRequestId && apiBase === state.apiBase;
  $<HTMLButtonElement>("windowRefresh").disabled = true;
  $("windowRefresh").setAttribute("aria-label", "正在刷新");
  $<HTMLButtonElement>("refresh").disabled = true;
  $("refresh").textContent = "刷新中...";
  setAutoRefreshStatus(silent ? "自动刷新中..." : "刷新中...");
  try {
    if (await loadOverview() === false || !current()) return;
    if (!silent) {
      await loadRegions({ silent: true });
      if (!current()) return;
    }
    await loadItems();
    if (!current()) return;
    state.lastRefreshAt = new Date();
    setAutoRefreshStatus(`最后刷新 ${formatRefreshTime(state.lastRefreshAt)}；每 60 秒自动刷新`);
  } catch (error) {
    if (!current()) return;
    $("connectionStatus").innerHTML = `<span class="error">连接失败：${esc(errorMessage(error))}。请确认 crow-api 在 ${esc(state.apiBase)} 运行。</span>`;
    if (!state.lastOverview) {
      $("cards").innerHTML = '<div class="empty-state error">运行指标读取失败，等待重新连接。</div>';
      $("items").innerHTML = '<tr><td colspan="4" class="empty-state error">尚未读取商品列表，请恢复连接后刷新。</td></tr>';
      $<HTMLButtonElement>("prev").disabled = true;
      $<HTMLButtonElement>("next").disabled = true;
    }
    setAutoRefreshStatus(`刷新失败；每 60 秒自动重试`);
    $("overviewNotice").textContent = state.lastOverview
      ? "连接或数据读取失败；运行指标保留上次快照，不代表当前实时状态。"
      : "尚未读取到运行状态。请检查 API 地址，恢复连接后刷新。";
    $("overviewNotice").classList.remove("hidden");
  } finally {
    if (current()) {
      state.refreshInFlight = false;
      $<HTMLButtonElement>("windowRefresh").disabled = false;
      $("windowRefresh").setAttribute("aria-label", "刷新");
      $<HTMLButtonElement>("refresh").disabled = false;
      $("refresh").textContent = "刷新数据";
    }
  }
}

async function refreshList() {
  try { await loadItems(); } catch { /* The list keeps its own error state. */ }
}

async function runDetailAction(action: () => void | Promise<void>): Promise<void> {
  const requestId = state.detailRequestId;
  setDetailBusy(true);
  try { await action(); }
  catch (error) {
    if (requestId === state.detailRequestId) setDetailActionStatus(`操作失败：${errorMessage(error)}`, "bad");
  } finally {
    if (requestId === state.detailRequestId) setDetailBusy(false);
  }
}

async function reloadAfterDetailAction({ requestId, includeOverview = false }: { requestId: number; includeOverview?: boolean }): Promise<void> {
  try {
    if (includeOverview) await loadOverview();
    await loadItems();
  } catch (error) {
    if (requestId === state.detailRequestId) setDetailActionStatus(`操作已提交，但状态刷新失败：${errorMessage(error)}。请刷新查看，不必重复提交。`, "warn");
  }
}

registerActions({
  hideDetailPanel,
  loadItems: refreshList,
  loadOverview,
  openAuthChallenge,
  reloadAll,
  reloadAfterDetailAction,
  toggleRuntimePause,
  requestEngineRestart,
});

document.querySelectorAll<HTMLButtonElement>("button[data-stage]").forEach((button) =>
  button.addEventListener("click", async () => {
    if (!isCollectionStage(button.dataset.stage)) return;
    document.querySelectorAll("button[data-stage]").forEach((candidate) => {
      candidate.classList.remove("active");
      candidate.setAttribute("aria-pressed", "false");
    });
    button.classList.add("active");
    button.setAttribute("aria-pressed", "true");
    state.stage = button.dataset.stage;
    state.offset = 0;
    state.itemsRequestId += 1;
    hideDetailPanel();
    await loadRegions();
    await refreshList();
  }),
);

$("limit").addEventListener("change", async () => {
  state.limit = Number($<HTMLSelectElement>("limit").value || 100);
  state.offset = 0;
  await refreshList();
});
$("refresh").addEventListener("click", () => void reloadAll());
$("prev").addEventListener("click", async () => {
  state.offset = Math.max(0, state.offset - state.limit);
  await refreshList();
});
$("next").addEventListener("click", async () => {
  if (state.offset + state.limit < state.total) {
    state.offset += state.limit;
  }
  await refreshList();
});
$("applyApiBase").addEventListener("click", async () => {
  hideDetailPanel();
  setConfigurationBlocked(false);
  state.apiBase = $<HTMLInputElement>("apiBase").value.trim() || defaultBrowserApiBase();
  state.offset = 0;
  state.selectedProvince = "";
  state.selectedCity = "";
  state.selectedLocationCode = "";
  state.regions = [];
  state.lastOverview = null;
  state.refreshRequestId += 1;
  state.refreshInFlight = false;
  state.overviewRequestId += 1;
  state.itemsRequestId += 1;
  $("cards").innerHTML = '<div class="empty-state">正在读取运行与采集指标...</div>';
  resetOverviewHistory();
  $<HTMLInputElement>("restartToken").value = "";
  resetRuntimeSettings();
  resetAuthChallenge();
  await reloadAll();
});
$("closeDetail").addEventListener("click", () => {
  document.querySelector<HTMLElement>("tr.item-row.selected")?.focus();
  hideDetailPanel();
});
$("reanalysisButton").addEventListener("click", () => runDetailAction(requestReanalysis));
$("editButton").addEventListener("click", () => runDetailAction(async () => {
  if (state.editingAnalysis) {
    await cancelManualEdit();
  } else {
    startManualEdit();
  }
}));
$("manualUpdateButton").addEventListener("click", () => runDetailAction(submitManualUpdate));
$("authChallengeReload").addEventListener("click", reloadAuthChallenge);
$("authChallengeResume").addEventListener("click", resumeAfterAuthChallenge);
$("refreshRegions").addEventListener("click", () => loadRegions({ silent: false }));
$("resetRegionLinks").addEventListener("click", resetSelectedRegionLinks);

const initialConfig = await startupApiBase(() => tryInvoke("default_api_base"), defaultBrowserApiBase);
state.apiBase = initialConfig.apiBase;
$<HTMLInputElement>("apiBase").value = state.apiBase;
setConfigurationBlocked(initialConfig.blocked);
resetRuntimeSettings();
if (initialConfig.blocked) {
  $("connectionStatus").textContent = CONFIGURATION_ERROR;
  setAutoRefreshStatus("配置冲突，自动请求已暂停");
} else {
  await reloadAll();
}
setInterval(() => { if (!isConfigurationBlocked()) void reloadAll({ silent: true }); }, AUTO_REFRESH_INTERVAL_MS);
setInterval(() => { if (!isConfigurationBlocked()) void loadRegions({ silent: true }); }, REGION_REFRESH_INTERVAL_MS);
