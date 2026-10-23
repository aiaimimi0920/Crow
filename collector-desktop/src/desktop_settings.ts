import { object } from "./desktop_value.ts";
import { element } from "./desktop_dom.ts";
import { controlOrigin, groups, readConfig, type Config } from "./desktop_settings_contract.ts";
import { localCollectionDefaults } from "./collection_defaults.ts";
import { draftKey, loadDraft, saveDraft, type Baseline } from "./desktop_settings_draft.ts";
import { settingsTemplate } from "./desktop_settings_template.ts";
import { installedControlOrigin, settingsRequest } from "./desktop_settings_transport.ts";
import { settingsWaitExpired } from "./desktop_settings_wait.ts";

export function initializeSettings(apiBase: () => string, showDialog: (dialog: HTMLDialogElement) => void): () => void {
  element("runtimeSettings").innerHTML = settingsTemplate;
  let baseline: Baseline | null = null;
  let generation = 0;
  let edits = 0;
  let activeKey = "";
  let dirty = false;
  let busy = false;
  let pending = false;
  let polling = false;
  let activeRequests = 0;
  let pollFailures = 0;
  let operationId = "";
  let operationStartedAt: number | null = null;
  let pollTimer: ReturnType<typeof setTimeout> | undefined;
  const status = (text: string) => { element("settingsStatus").textContent = text; };
  const source = (text: string) => { element("settingsConfigSource").textContent = text; };
  const secret = () => element<HTMLInputElement>("settingsAiKey");
  const config = () => readConfig((name) => name === "ai.allow_gpt"
    ? String(element<HTMLInputElement>(`setting-${name}`).checked)
    : element<HTMLInputElement>(`setting-${name}`).value);
  const buttons = () => {
    element<HTMLButtonElement>("settingsApply").disabled = busy || pending || activeRequests > 0;
    element<HTMLButtonElement>("settingsLoad").disabled = busy || activeRequests > 0;
    element<HTMLButtonElement>("settingsStatusRefresh").disabled = busy || activeRequests > 0;
    // Offline or pending operations must not prevent editing the next draft.
    element<HTMLFieldSetElement>("runtimeSettingsFields").disabled = false;
  };
  const fill = (value: Config) => {
    for (const group of groups) for (const field of group.fields) {
      element<HTMLInputElement>(`setting-${group.key}.${field[0]}`).value = String(value[group.key][field[0]]);
    }
    element<HTMLInputElement>("setting-ai.allow_gpt").checked = value.ai.allow_gpt === true;
    element<HTMLSelectElement>("setting-ai.reasoning_effort").value = String(value.ai.reasoning_effort || "none");
  };
  const restore = () => {
    baseline = null; dirty = false; fill(localCollectionDefaults);
    source("本地默认值 · 当前部署配置快照");
    try {
      activeKey = draftKey(apiBase());
      const draft = loadDraft(localStorage, activeKey);
      if (draft) { fill(draft.config); baseline = draft.baseline; dirty = true; source("本机草稿 · 尚未应用"); }
    } catch (error) { status(error instanceof Error ? error.message : "读取草稿失败"); }
  };
  const save = () => {
    const value = config();
    saveDraft(localStorage, draftKey(apiBase()), { config: value, baseline });
    dirty = true; source("本机草稿 · 尚未应用");
    return value;
  };
  const reset = () => {
    for (const name of ["settingsApplyDialog", "settingsReloadDialog"]) {
      const dialog = element<HTMLDialogElement>(name);
      if (dialog.open) dialog.close("cancel");
    }
    generation += 1; busy = false; pending = false; polling = false;
    operationId = ""; operationStartedAt = null;
    clearTimeout(pollTimer);
    element("settingsKeyStatus").textContent = "";
    status("连接或授权已变化；草稿可继续编辑，应用前将重新校验线上配置。");
    try { if (draftKey(apiBase()) !== activeKey) restore(); }
    catch { status("API 地址无效；未发送配置或凭据。"); }
    buttons();
  };
  const endpoint = () => controlOrigin(element<HTMLInputElement>("settingsControlBase").value.trim() || apiBase());
  const token = () => element<HTMLInputElement>("restartToken").value.trim();
  async function confirm(name: string): Promise<boolean> {
    const dialog = element<HTMLDialogElement>(name);
    dialog.returnValue = "cancel";
    const decision = new Promise<string>((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue), { once: true }));
    showDialog(dialog);
    return await decision === "confirm";
  }
  async function request(path: string, body?: unknown): Promise<Record<string, unknown>> {
    const origin = endpoint();
    activeRequests += 1; buttons();
    try {
      return await settingsRequest(origin, path, token(), body);
    } finally { activeRequests -= 1; buttons(); }
  }
  const showState = (value: Record<string, unknown>) => {
    const receipt = object(value.request);
    const labels: Record<string, string> = { requested: "已保存，等待 PC2 应用", applying: "PC2 正在应用配置", succeeded: "参数已应用，容器健康检查通过（不代表 AI 推理成功）", failed: "应用失败，请检查结果和生效配置", expired: "请求已过期，未被 PC2 领取", unknown: "应用结果未确认，需检查 PC2，不能继续提交" };
    status(`${value.available ? "PC2 控制器在线" : "PC2 控制器离线"} · 配置版本 ${value.revision ?? "未知"}${receipt.status ? ` · ${labels[String(receipt.status)] || "未知状态"}` : ""}`);
    pending = ["requested", "applying", "unknown"].includes(String(receipt.status));
    polling = ["requested", "applying"].includes(String(receipt.status));
    if (operationId !== String(receipt.id || "")) {
      operationId = String(receipt.id || ""); operationStartedAt = null;
    }
    if (polling && operationStartedAt === null) operationStartedAt = Date.now();
    if (!pending) operationStartedAt = null;
    if (settingsWaitExpired(operationStartedAt, Date.now())) {
      polling = false;
      status("PC2 应用结果等待超过 12 分钟，已停止自动查询；请刷新状态确认。草稿仍可编辑，未自动重放操作。");
    }
    pollFailures = 0;
  };
  const schedulePoll = () => {
    clearTimeout(pollTimer);
    if (polling) pollTimer = setTimeout(() => void load(false), 3000);
  };
  const liveConfig = (value: Record<string, unknown>): Config => {
    if (typeof value.revision !== "number" || !Number.isInteger(value.revision)) throw new Error("尚无控制器上报的真实配置");
    const effective = object(value.effective);
    return readConfig((name) => { const [group, field] = name.split("."); return String(object(effective[group])[field] ?? ""); });
  };
  async function load(populate: boolean) {
    if (busy || activeRequests > 0) return;
    const id = generation;
    const editVersion = edits;
    let pollFailureEligible = !populate;
    busy = true; buttons();
    try {
      if (populate && dirty && !await confirm("settingsReloadDialog")) return;
      if (id !== generation) return;
      const origin = endpoint();
      const value = await request("");
      if (id !== generation) return;
      showState(value);
      // Once transport succeeded, malformed effective config is a response
      // contract problem and must not consume the transient poll retry budget.
      pollFailureEligible = false;
      const effective = liveConfig(value);
      if (populate) {
        if (editVersion !== edits) throw new Error("读取期间编辑内容已变化；已保留编辑内容，请重试");
        fill(effective); baseline = { origin, revision: Number(value.revision) }; secret().value = "";
        localStorage.removeItem(draftKey(apiBase())); dirty = false;
        source("线上生效配置");
      } else if (!pending) {
        let matches = false;
        try { matches = JSON.stringify(config()) === JSON.stringify(effective); }
        catch { /* An unfinished draft does not make a successful status poll fail. */ }
        if (matches) {
          baseline = { origin, revision: Number(value.revision) };
          saveDraft(localStorage, draftKey(apiBase()), { config: effective, baseline });
          source("编辑内容与线上生效配置一致");
        }
      }
      element("settingsKeyStatus").textContent = value.api_key_configured ? "当前 AI 密钥已配置" : "当前未配置 AI 密钥";
    } catch (error) {
      if (id === generation) {
        if (pollFailureEligible && ++pollFailures >= 5) polling = false;
        status(error instanceof Error ? error.message : "读取失败；已保留编辑内容");
      }
    }
    finally { if (id === generation) { busy = false; buttons(); schedulePoll(); } }
  }
  element("runtimeSettingsForm").addEventListener("input", () => { edits += 1; dirty = true; source("编辑中 · 尚未保存或应用"); });
  element("settingsLoad").addEventListener("click", () => void load(true));
  element("settingsStatusRefresh").addEventListener("click", () => void load(false));
  element("settingsControlBase").addEventListener("change", reset);
  element("restartToken").addEventListener("change", reset);
  element("settingsSaveDraft").addEventListener("click", () => {
    try { save(); status("草稿已保存到本机，尚未应用到 PC2；AI 密钥不会写入草稿。"); }
    catch (error) { status(error instanceof Error ? error.message : "草稿保存失败"); }
  });
  element("runtimeSettingsForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || pending || activeRequests > 0) return;
    const id = generation;
    const editVersion = edits;
    let submitted = false;
    let saved = false;
    try {
      const edited = save(); saved = true;
      busy = true; buttons();
      const origin = endpoint();
      const value = await request("");
      if (id !== generation) return;
      showState(value); liveConfig(value);
      if (pending) throw new Error("已有配置操作未完成，请刷新应用状态；草稿可继续编辑");
      if (value.available !== true) throw new Error("PC2 控制器离线，未应用；草稿已保留");
      if (baseline && (baseline.origin !== origin || baseline.revision !== value.revision)) throw new Error("线上配置版本或控制地址已变化，请读取线上配置后重新编辑；未覆盖线上配置");
      if (editVersion !== edits) throw new Error("校验期间编辑内容已变化，请重新保存并应用");
      if (!await confirm("settingsApplyDialog") || id !== generation) return;
      const body = { request_id: crypto.randomUUID(), expected_revision: value.revision, config: edited, api_key: secret().value || null };
      secret().value = ""; submitted = true; pending = true; polling = true; pollFailures = 0;
      const result = await request("/apply", body);
      if (id === generation) {
        const receipt = object(result.request);
        const requestedRevision = receipt.revision;
        if (receipt.id !== body.request_id || typeof requestedRevision !== "number" || !Number.isInteger(requestedRevision) || !["requested", "applying", "succeeded", "failed", "expired", "unknown"].includes(String(receipt.status))) throw new Error("应用回执无效，请刷新状态确认结果");
        baseline = { origin, revision: requestedRevision };
        if (edits === editVersion) saveDraft(localStorage, draftKey(apiBase()), { config: edited, baseline });
        showState({ ...result, revision: requestedRevision, available: true });
        source(edits === editVersion ? "本机草稿 · 已提交，等待 PC2 确认" : "编辑中 · 上一版已提交，当前修改未提交");
      }
    } catch (error) {
      if (id === generation) status(`${submitted ? "提交结果需刷新确认" : saved ? "草稿已保存，未应用" : "未保存、未应用"} · ${error instanceof Error ? error.message : "请求失败"}`);
    } finally { if (id === generation) { busy = false; buttons(); schedulePoll(); } }
  });
  restore(); buttons();
  void installedControlOrigin().then((origin) => {
    if (origin && !element<HTMLInputElement>("settingsControlBase").value) {
      element<HTMLInputElement>("settingsControlBase").value = origin;
      void load(false);
    }
  }).catch(() => status("本机安全控制组件未配置；草稿可继续编辑保存。"));
  return reset;
}
