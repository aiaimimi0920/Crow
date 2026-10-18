import { callAction } from "./desktop_actions.ts";
import { state } from "./desktop_state.ts";
import { isTauriRuntime, tryInvoke } from "./desktop_native.ts";
import { $, showManagedDialog, closeManagedDialog, getJson } from "./desktop_shared.ts";
import { authScopeState, authScopeTarget, scopeLabel, type AuthScope } from "./desktop_auth_scope.ts";
import { authResult, authWaitState } from "./desktop_auth_contract.ts";
import { errorMessage, object } from "./desktop_value.ts";
import { recordArray } from "./desktop_collection_contract.ts";
import { AUTH_POLL_INTERVAL_MS } from "./desktop_config.ts";

interface AuthSession {
  api_base: string;
  scope: AuthScope;
  target_url: string;
  challenge_id: string;
  target_id: string;
  recovery_id: string;
  request_id: string;
  browser?: "dedicated" | "edge";
  peer_url?: string;
  peer_challenge_id?: string;
}

let session: AuthSession | null = null;
let phase = "";
let busy = false;
let generation = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
let wired = false;
let waitStartedAt: number | null = null;
const sessions = new Map<AuthScope, { session: AuthSession; phase: string; waitStartedAt: number | null }>();
const sharedStorageKey = "crow.sharedAuth";

function rememberShared() {
  try {
    if (phase === "pending_pc2" && session?.recovery_id?.startsWith("shared-auth-")) {
      localStorage.setItem(sharedStorageKey, JSON.stringify({ session, waitStartedAt }));
    } else localStorage.removeItem(sharedStorageKey);
  } catch { /* Storage failure must not interrupt an acknowledged handoff. */ }
}

function statusText(message: string): void {
  $("authChallengeStatus").textContent = `${session?.recovery_id?.startsWith("shared-auth-") ? "链接与详情采集" : scopeLabel(session?.scope || "seed")}：${message}`;
}

function controls() {
  $<HTMLButtonElement>("authChallengeReload").disabled = busy || phase === "pending_pc2";
  $<HTMLButtonElement>("authChallengeEdge").disabled = busy || phase === "pending_pc2";
  $<HTMLButtonElement>("authChallengeResume").disabled = busy;
}

export function resetAuthChallenge() {
  generation += 1;
  clearTimeout(timer);
  session = null;
  sessions.clear();
  phase = "";
  busy = false;
  waitStartedAt = null;
  const dialog = $<HTMLDialogElement>("authChallengeDialog");
  if (dialog.open) closeManagedDialog(dialog);
}

export function openAuthChallenge(scope: AuthScope = "seed"): void {
  if (busy || !["seed", "detail"].includes(scope)) return;
  if (!session) {
    try {
      const saved = object(JSON.parse(localStorage.getItem(sharedStorageKey) || "null"));
      const candidate = object(saved.session);
      if (candidate.api_base === state.apiBase && typeof candidate.recovery_id === "string"
          && /^shared-auth-[a-f0-9]{32}$/.test(candidate.recovery_id)
          && (candidate.scope === "seed" || candidate.scope === "detail")) {
        session = {
          api_base: state.apiBase, scope: candidate.scope, recovery_id: candidate.recovery_id,
          target_url: String(candidate.target_url || ""), challenge_id: String(candidate.challenge_id || ""),
          target_id: String(candidate.target_id || ""), request_id: String(candidate.request_id || ""),
          peer_url: String(candidate.peer_url || ""), peer_challenge_id: String(candidate.peer_challenge_id || ""),
          browser: candidate.browser === "edge" ? "edge" : "dedicated",
        };
        phase = "pending_pc2";
        waitStartedAt = typeof saved.waitStartedAt === "number" && Number.isFinite(saved.waitStartedAt)
          ? saved.waitStartedAt : Date.now();
      }
    } catch { /* Invalid local UI metadata is ignored. */ }
  }
  if (phase === "pending_pc2" && session?.recovery_id?.startsWith("shared-auth-")) scope = session.scope;
  if (session && session.scope !== scope) {
    sessions.set(session.scope, { session, phase, waitStartedAt });
    generation += 1;
    clearTimeout(timer);
    const saved = sessions.get(scope);
    session = saved?.session || null;
    phase = saved?.phase || "";
    waitStartedAt = saved?.waitStartedAt ?? null;
  }
  const dialog = $<HTMLDialogElement>("authChallengeDialog");
  if (!wired) {
    dialog.addEventListener("close", () => {
      if (!session?.recovery_id?.startsWith("shared-auth-")) clearTimeout(timer);
    });
    dialog.addEventListener("click", (event) => {
      const box = dialog.getBoundingClientRect();
      if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) closeManagedDialog(dialog);
    });
    wired = true;
  }
  if (!session || session.api_base !== state.apiBase || ["failed", "succeeded"].includes(phase)) {
    session = { api_base: state.apiBase, scope, target_url: authScopeTarget(state.lastOverview, scope, state.selectedItemId),
      challenge_id: String(authScopeState(state.lastOverview, scope)?.challenge_id || ""),
      target_id: "", recovery_id: "", request_id: crypto.randomUUID().replaceAll("-", "") };
    phase = "";
    waitStartedAt = null;
  }
  dialog.setAttribute("aria-label", `${scopeLabel(scope)}人工认证`);
  dialog.dataset.scope = scope;
  statusText(phase === "pending_pc2" ? "等待 PC2 验证此阶段。" : "请打开挑战页面，完成后提交。");
  controls();
  showManagedDialog(dialog);
  if (phase === "pending_pc2") void run("status");
}

async function run(action: "open" | "complete" | "status"): Promise<void> {
  if (busy || !session) return;
  const id = generation;
  const current = session;
  busy = true;
  clearTimeout(timer);
  controls();
  // Background status checks must not replace the last acknowledged stage.
  if (action !== "status") statusText(action === "open" ? "正在打开挑战页面…" : "正在验证并同步认证会话…");
  try {
    if (action === "open" || (action === "complete" && !current.recovery_id)) {
      const overview = await getJson("/api/collection/overview");
      if (id !== generation || current !== session) return;
      state.lastOverview = overview;
      if (action === "open") {
        current.target_url = authScopeTarget(overview, current.scope, state.selectedItemId);
        current.challenge_id = String(authScopeState(overview, current.scope)?.challenge_id || "");
      }
    }
    if (action === "open" && current.scope === "detail" && !current.target_url) {
      const items = await getJson("/api/collection/items?stage=links&limit=1&offset=0");
      if (id !== generation || current !== session) return;
      const item = recordArray(items.items)[0];
      current.target_url = authScopeTarget(state.lastOverview, "detail", item?.item_id || item?.id);
      if (!current.target_url) { statusText("暂无可认证的商品详情，请先选择一个商品后重试。"); return; }
    }
    if (!isTauriRuntime()) {
      if (action === "open") window.open(current.target_url, "_blank", "noopener,noreferrer");
      $("authChallengeStatus").textContent = "请使用桌面版同步认证会话；普通浏览器无法读取挑战窗口的 cookie。";
      return;
    }
    if (action === "complete") {
      const peer = current.scope === "seed" ? "detail" : "seed";
      current.peer_url = authScopeTarget(state.lastOverview, peer, state.selectedItemId);
      current.peer_challenge_id = String(authScopeState(state.lastOverview, peer)?.challenge_id || "");
      if (!current.peer_url && peer === "detail") {
        const items = await getJson("/api/collection/items?stage=links&limit=1&offset=0");
        if (id !== generation || current !== session) return;
        const item = recordArray(items.items)[0];
        current.peer_url = authScopeTarget(state.lastOverview, peer, item?.item_id || item?.id);
      }
      if (!current.peer_url) { statusText("暂无详情验证目标，请先选择一个商品后提交；已完成的浏览器认证仍可复用。"); return; }
    }
    const response = object(await tryInvoke("desktop_auth_action", { request: { ...current, action } }));
    if (id !== generation || current !== session) return;
    const result = authResult(response);
    phase = result.phase;
    if (typeof response.target_id === "string") current.target_id = response.target_id;
    if (typeof response.recovery_id === "string") current.recovery_id = response.recovery_id;
    if (phase === "pending_pc2" && waitStartedAt === null) waitStartedAt = Date.now();
    if (phase !== "pending_pc2") waitStartedAt = null;
    rememberShared();
    const wait = authWaitState(waitStartedAt, Date.now());
    statusText(wait.poll ? result.message : `${result.message} ${wait.hint}`);
    if (result.completed) {
      closeManagedDialog($<HTMLDialogElement>("authChallengeDialog"));
      await callAction("reloadAll");
    } else if (phase === "pending_pc2" && wait.poll && ($<HTMLDialogElement>("authChallengeDialog").open || response.shared)) {
      timer = setTimeout(() => void run("status"), AUTH_POLL_INTERVAL_MS);
    }
  } catch (error) {
    if (id === generation) $("authChallengeStatus").textContent = `认证同步未完成：${errorMessage(error)}`;
  } finally {
    if (id === generation) { busy = false; controls(); }
  }
}

export function reloadAuthChallenge(browser: "dedicated" | "edge" = "dedicated") {
  if (busy || phase === "pending_pc2") return;
  if (session && session.browser !== browser) {
    session.browser = browser;
    phase = "failed";
  }
  if ((phase === "failed" || browser === "edge") && session) {
    session.request_id = crypto.randomUUID().replaceAll("-", "");
    session.target_url = authScopeTarget(state.lastOverview, session.scope, state.selectedItemId);
    session.challenge_id = String(authScopeState(state.lastOverview, session.scope)?.challenge_id || "");
    session.target_id = "";
    session.recovery_id = "";
    waitStartedAt = null;
  }
  return run("open");
}

export function resumeAfterAuthChallenge() {
  return run(phase === "pending_pc2" ? "status" : "complete");
}
