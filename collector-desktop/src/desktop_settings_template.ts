import { groups } from "./desktop_settings_contract.ts";
import { defaultsObservedAt } from "./collection_defaults.ts";

export const settingsTemplate = `<summary><strong>采集运行配置</strong></summary><div class="settings-body">
  <label class="settings-control-address">安全控制地址 <input id="settingsControlBase" placeholder="HTTPS 地址或 http://127.0.0.1:18001" /></label>
  <div class="toolbar"><button id="settingsLoad" type="button">读取线上配置</button><button id="settingsStatusRefresh" type="button">刷新应用状态</button></div>
  <p id="settingsStatus" class="status-line" role="status" aria-live="polite">可编辑并保存草稿；保存并应用时校验线上配置。</p>
  <p id="settingsConfigSource" class="status-line" title="${defaultsObservedAt}">本地默认值 · 当前部署配置快照</p>
  <form id="runtimeSettingsForm"><fieldset id="runtimeSettingsFields">
  ${groups.map((group) => `<section class="runtime-settings-group"><h2>${group.label}</h2><div class="runtime-settings-grid">${group.fields.map((field) => `<label>${field[1]}<input id="setting-${group.key}.${field[0]}" ${field.length === 4 ? `type="number" min="${field[2]}" max="${field[3]}" step="${field[0].endsWith("delay") ? "0.1" : "1"}"` : 'type="text"'} required /></label>`).join("")}</div></section>`).join("")}
  <label class="settings-toggle"><input id="setting-ai.allow_gpt" type="checkbox" />允许使用 GPT 模型（PC2 AI 归档）</label>
  <p class="status-line">默认关闭。开启后可填写 GPT / Codex / o 系列路由，可能产生模型费用；不会自动解除采集暂停。关闭时请同时选择非 GPT 模型。</p>
  <label>推理强度 <select id="setting-ai.reasoning_effort">${["none", "minimal", "low", "medium", "high", "xhigh"].map((value) => `<option value="${value}">${value}</option>`).join("")}</select></label>
  <label class="settings-secret">AI API Key <input id="settingsAiKey" type="password" autocomplete="new-password" placeholder="留空保留当前密钥，不回显，不写入草稿" /></label>
  <p id="settingsKeyStatus" class="status-line"></p>
  <p class="status-line">人工认证失败次数阈值尚未接入本版本；保持现有认证策略。</p>
  <div class="toolbar"><button id="settingsSaveDraft" type="button">保存草稿</button><button id="settingsApply" type="submit" class="primary-button">保存并应用</button></div>
  </fieldset></form></div>
  <dialog id="settingsApplyDialog" class="auth-dialog" aria-labelledby="settingsApplyTitle">
    <h2 id="settingsApplyTitle">应用采集配置</h2><p>将用编辑内容更新 PC2，并重建受影响的 Worker，可能中断在途采集。数据库、浏览器和持久挂载不删除；失败时尝试回滚配置。</p>
    <form method="dialog" class="toolbar"><button value="cancel" autofocus>取消</button><button value="confirm" class="primary-button">确认应用</button></form>
  </dialog>
  <dialog id="settingsReloadDialog" class="auth-dialog" aria-labelledby="settingsReloadTitle">
    <h2 id="settingsReloadTitle">读取线上配置</h2><p>用线上生效配置替换当前编辑内容和本机草稿？尚未提交的 AI 密钥也会清空。</p>
    <form method="dialog" class="toolbar"><button value="cancel" autofocus>取消</button><button value="confirm" class="primary-button">替换</button></form>
  </dialog>`;
