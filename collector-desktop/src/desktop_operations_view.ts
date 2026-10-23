import { object } from "./desktop_value.ts";
import { escapeHtml as esc } from "./desktop_dom.ts";
import { authScopeState, scopeLabel, type AuthScope } from "./desktop_auth_scope.ts";

export const count = (value: unknown): string => typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString("zh-CN") : "—";
export const epoch = (value: unknown): string => typeof value === "number" && Number.isFinite(value) && value > 0 && value < 1e11
  ? new Date(value * 1000).toLocaleString("zh-CN", { hour12: false }) : "—";
export const pair = (label: string, value: string): string => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`;

const reasonLabels: Record<string, string> = {
  operator: "操作员暂停", captcha_solver: "等待挑战处理", manual_required: "需要人工认证",
  challenge_retry_exhausted: "本轮挑战尝试已耗尽", solver_failed: "自动求解未通过",
  node_solver_blocked: "节点求解受阻", solver_cooldown: "自动求解冷却",
  force_reset_required: "需要重新认证", timeout: "处理超时", solver_timeout: "求解超时",
  repeated_solver_failures: "节点连续求解失败；等待退避或人工介入",
  challenge: "检测到挑战", captcha: "检测到验证码", manual_only: "仅人工认证",
};
export function reason(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未报告";
  return typeof value === "string" && Object.hasOwn(reasonLabels, value) ? reasonLabels[value] : "未分类原因（原始内容不展示）";
}

function scopeView(value: unknown, scope: AuthScope): string {
  const state = authScopeState(value, scope);
  if (!state) return `<article class="ops-scope"><h3>${scopeLabel(scope)}</h3><p class="status-line">状态未上报，不能判定已恢复。</p></article>`;
  const active = state.last_status === "running" || state.last_status === "queued";
  const attention = state.manual_required === true || state.force_reset_required === true || state.node_solver_blocked === true;
  const label = attention ? "需要认证 / 介入" : active ? "挑战处理中" : state.paused === true ? "阶段暂停" : "未报告挑战";
  return `<article class="ops-scope"><h3>${scopeLabel(scope)} <span class="pill ${attention ? "bad" : active || state.paused ? "warn" : "ok"}">${label}</span></h3>
    <dl class="ops-facts">${pair("暂停原因", reason(state.pause_reason))}${pair("最近失败", reason(state.last_failure_reason))}
    ${pair("节点阻塞", reason(state.node_solver_blocked_reason))}${pair("节点已报告尝试", count(state.node_solver_blocked_attempts))}
    ${pair("挑战首次出现", epoch(state.first_seen_epoch))}${pair("暂停开始", epoch(state.pause_started_epoch))}</dl></article>`;
}

const receiptLabels: Record<string, string> = {
  requested: "已提交，等待接收", restarting: "正在重启", applying: "正在应用", succeeded: "已完成",
  failed: "执行失败", expired: "请求已过期", unknown: "结果未确认；禁止重复提交",
};
const resultLabels: Record<string, string> = {
  workers_ready: "Worker 健康检查通过（不等于业务成功）", restart_failed: "Worker 重启失败",
  health_timeout: "健康检查超时", controller_interrupted: "控制器执行中断",
  settings_drift: "线上配置与部署计划不一致", command_timeout: "执行命令超时",
  transport_or_filesystem_unavailable: "传输或文件系统不可用",
};
export function renderReceipt(value: unknown): string {
  const request = object(value);
  const id = typeof request.id === "string" && /^[a-zA-Z0-9_-]{1,80}$/.test(request.id) ? request.id : "—";
  const label = typeof request.status === "string" && Object.hasOwn(receiptLabels, request.status) ? receiptLabels[request.status] : "暂无有效回执";
  const result = typeof request.result === "string" && Object.hasOwn(resultLabels, request.result) ? resultLabels[request.result] : request.result ? "已记录；需核查控制器证据" : "—";
  return `<dl class="ops-facts">${pair("操作状态", label)}${pair("请求编号", id)}${pair("结果", result)}${pair("更新时间", epoch(request.updated))}</dl>`;
}

export function operationsFreshness(value: unknown, receivedAt: number, failed: boolean, now = Date.now()): { text: string; warning: boolean } {
  const statistics = object(object(object(value).status).statistics);
  const age = Math.max(0, Math.floor((now - receivedAt) / 1000));
  const stale = failed || age > 90 || statistics.stale === true;
  const valid = statistics.valid !== false;
  return { warning: stale || !valid, text: `${!valid ? "统计不可用" : stale ? "快照陈旧 / 刷新失败" : "NAS 快照已接收"} · 本机接收 ${new Date(receivedAt).toLocaleTimeString("zh-CN", { hour12: false })} · ${age} 秒前` };
}

export function renderOperations(value: unknown, receivedAt: number, failed: boolean, now = Date.now()): string {
  if (!value) return '<div class="empty-state">尚未收到 NAS 状态。请刷新；缺少数据不代表任务为零或系统正常。</div>';
  const data = object(value), status = object(data.status), modules = object(data.modules);
  const statistics = object(status.statistics), solver = object(status.captcha_solver);
  const freshness = operationsFreshness(value, receivedAt, failed, now);
  const valid = statistics.valid !== false;
  const number = (value: unknown) => valid ? count(value) : "—";
  const details = object(modules.details), analysis = object(modules.analysis);
  const rows = [
    ["链接扫描任务", status.seed_scan_job_completed, status.seed_scan_job_pending, status.seed_scan_job_in_progress, status.seed_scan_job_failed, status.seed_scan_job_blocked],
    ["详情商品", details.captured, details.pending, status.seed_item_in_progress, details.failed, details.blocked],
    ["AI 归档商品", analysis.finalized, analysis.pending, status.analysis_in_progress_count, analysis.failed, analysis.blocked],
  ];
  const next = solver.manual_retry_next_epoch;
  const retry = typeof next === "number" && Number.isFinite(next) && next > 0
    ? `${epoch(next)}（计划时间；是否执行以新状态为准）` : "未安排 / 未上报";
  return `<div id="operationsFreshness" class="ops-freshness ${freshness.warning ? "warn" : "ok"}" role="status">${esc(freshness.text)}</div>
    <section class="ops-section"><h2>采集流水线</h2><div id="operationsQueue" class="ops-table-wrap" tabindex="0" role="region" aria-label="三阶段队列"><table class="ops-table"><thead><tr><th>阶段 / 单位</th><th>已完成</th><th>待处理</th><th>执行中</th><th>失败</th><th>阻塞</th></tr></thead><tbody>
    ${rows.map(([label, ...values]) => `<tr><th scope="row">${esc(label)}</th>${values.map((item) => `<td>${number(item)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
    <p class="status-line">详情和 AI 待处理数包含执行中；AI 待处理包含可重试失败，列之间不可直接相加。链接行按扫描任务计，不是唯一商品数。— 表示未上报或无效。</p>
    <dl class="ops-facts">${pair("唯一商品链接", number(object(modules.links).unique_items))}${pair("链接出现总次数", number(object(modules.links).total))}${pair("AI 可领取", number(analysis.ready))}</dl></section>
    <section class="ops-section"><h2>认证与自动恢复</h2><div class="ops-scopes">${scopeView(data, "seed")}${scopeView(data, "detail")}</div>
    <dl class="ops-facts">${pair("NAS 自动重试", solver.manual_retry_enabled === true ? "已启用" : solver.manual_retry_enabled === false ? "未启用" : "未上报")}${pair("NAS 重试次数", count(solver.manual_retry_attempts))}${pair("NAS 下次重试", retry)}
    ${pair("节点求解委托", solver.delegated_to_node_solver === true ? "已委托；不代表正在拖动" : solver.delegated_to_node_solver === false ? "未委托" : "未上报")}</dl>
    <p class="status-line">这里是 NAS 协调状态，不是 PC2 本地 solver 冷却。PC2 冷却轮次、拖动结果和 Worker 心跳尚未接入此接口；不以控制器在线推断业务正常。</p></section>`;
}
