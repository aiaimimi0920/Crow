import { authScopeChallenge, scopeLabel, type AuthScope } from "./desktop_auth_scope.ts";
import { object } from "./desktop_value.ts";
import { escapeHtml as escape } from "./desktop_dom.ts";

type Sample = { at: number; counts: number[] };
const history: Sample[] = [];
let sampleWindow: number | null = null;

export function uniqueCounts(value: unknown): number[] {
  if (object(object(object(value).status).statistics).valid === false) return [NaN, NaN, NaN];
  const modules = object(object(value).modules);
  return [["links", "unique_items"], ["details", "captured"], ["analysis", "finalized"]].map(([stage, key]) => {
    const count = object(modules[stage])[key];
    return typeof count === "number" && Number.isFinite(count) && count >= 0 ? count : NaN;
  });
}

export function resetOverviewHistory(): void { history.length = 0; }

export function minuteGrowth(counts: number[], now: number): (number | null)[] {
  // Keep manual refreshes without relabelling their short interval as one minute.
  if (history.length && (now <= history.at(-1)!.at || now - history.at(-1)!.at > 75_000)) resetOverviewHistory();
  while (history.length && history[0].at < now - 75_000) history.shift();
  const baseline = history.filter((sample) => sample.at <= now - 60_000).at(-1);
  sampleWindow = baseline ? Math.round((now - baseline.at) / 1000) : null;
  const growth = counts.map((count, index) => baseline && Number.isFinite(count) && Number.isFinite(baseline.counts[index])
    ? count - baseline.counts[index] : null);
  history.push({ at: now, counts });
  if (history.length > 150) history.splice(0, history.length - 150);
  return growth;
}

export function challengeActive(value: unknown): boolean | null {
  const data = object(value);
  const solverValue = object(data.status).captcha_solver;
  if (!solverValue || typeof solverValue !== "object") return null;
  const solver = object(solverValue);
  const scopes = Object.values(object(solver.scopes || solver.collection_scopes)).map(object);
  return Boolean(solver.running || solver.queued || solver.manual_required || solver.force_unlock_flag_exists
    || scopes.some((scope) => scope.paused || scope.manual_required || scope.force_reset_required)
    || (solver.paused && ["captcha_solver", "manual_required"].includes(String(solver.pause_reason))));
}

export function operatorPaused(value: unknown): boolean {
  const status = object(object(value).status);
  if (typeof status.operator_paused === "boolean") return status.operator_paused;
  const reason = object(status.captcha_solver).pause_reason;
  return Boolean(status.paused && (!reason || reason === "operator"));
}

export function renderOverview(value: unknown, runtimeState: string, now = performance.now()): string {
  const data = object(value);
  const paused = operatorPaused(data);
  const counts = uniqueCounts(data);
  const statistics = object(object(data.status).statistics);
  const hasServerSamples = Array.isArray(statistics.minute_delta);
  const growth = hasServerSamples
    ? [0, 1, 2].map((index) => {
      const delta: unknown = (statistics.minute_delta as unknown[])[index];
      return statistics.valid === true && statistics.stale !== true && typeof delta === "number" && Number.isFinite(delta) ? delta : null;
    })
    : minuteGrowth(counts, now);
  const windowSeconds = hasServerSamples ? statistics.window_seconds : sampleWindow;
  const growthHint = statistics.stale === true ? "统计暂未更新"
    : typeof windowSeconds === "number" ? `近 ${windowSeconds} 秒采样` : "NAS 尚未积累完整分钟采样";
  const restart = object(data.engine_restart);
  const request = object(restart.request);
  const pending = ["requested", "restarting", "unknown"].includes(String(request.status));
  const restartLabels: Record<string, string> = {
    requested: "等待 PC2 接收", restarting: "PC2 正在重启", succeeded: "Worker 已重启",
    failed: "重启失败，请检查 PC2", expired: "重启请求已过期", unknown: "重启结果未确认，请检查 PC2",
  };
  const restartHint = restartLabels[String(request.status)] || (restart.available ? "" : "重启控制器未连接");
  const stateClass = runtimeState === "运行中" || runtimeState === "已完成" ? "ok" : runtimeState === "待认证" ? "bad" : "warn";
  return `<div class="card runtime-card">
    <div class="label">运行状态</div><div class="value"><span class="pill ${stateClass}">${escape(runtimeState)}</span></div>
    <div class="card-actions"><button id="runtimePauseButton" data-action="${paused ? "start" : "pause"}">${paused ? "开始采集" : "暂停采集"}</button>
    <button id="engineRestartButton" class="danger-button" data-available="${Boolean(restart.available && !pending)}" disabled title="远程重启 PC2 采集 Worker">重启 PC2 采集</button></div>
    <div id="engineRestartStatus" class="growth-line restart-status" role="status">${escape(restartHint)}</div></div>
    <div class="card challenge-card">${(["seed", "detail"] as AuthScope[]).map((scope) => {
      const challenge = authScopeChallenge(data, scope);
      return `<div class="auth-stage-row"><div class="label">${scopeLabel(scope)}</div>
        <span class="pill ${challenge === null ? "warn" : challenge ? "bad" : "ok"}">${challenge === null ? "状态未知" : challenge ? "待认证" : "未报告挑战"}</span>
        <button id="${scope}AuthButton" class="secondary-button" aria-label="${scopeLabel(scope)}认证" title="在 PC1 主动认证${scopeLabel(scope)}，无需等待挑战报告">认证</button></div>`;
    }).join("")}</div>
    ${["商品链接", "商品详情", "商品分析"].map((label, index) => {
      const delta = growth[index];
      const text = statistics.stale === true ? "统计暂未更新" : delta === null ? "—" : delta >= 0 ? `+${delta}` : `${delta}（数量回退）`;
      return `<div class="card metric-card"><div class="label">${label}</div><div class="value">${Number.isFinite(counts[index]) ? counts[index] : "—"}</div>
      <div class="growth-line ${delta === null ? "pending-growth" : delta < 0 ? "negative-growth" : ""}" title="${escape(growthHint)}：唯一商品数量变化；不把短间隔刷新折算成分钟增量">${text}</div></div>`;
    }).join("")}`;
}
