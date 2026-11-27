import { object } from "./desktop_value.ts";
import { controlOrigin } from "./desktop_settings_contract.ts";
import { boundedSettingsRequest } from "./desktop_settings_wait.ts";
import { nativeInvoke, type NativeInvoke } from "./desktop_native.ts";
import { fetchWithTimeout } from "./desktop_http.ts";
import { CONTROL_TIMEOUT_MS } from "./desktop_config.ts";

let nativeQueue: Promise<unknown> = Promise.resolve();

function invokeControl(invoke: NativeInvoke, request: Record<string, unknown>): Promise<unknown> {
  const timeoutMs = request.action === "apply" ? 95_000 : 40_000;
  const operation = nativeQueue.then(() => boundedSettingsRequest(invoke("desktop_settings_action", { request }), timeoutMs));
  nativeQueue = operation.catch(() => undefined);
  return operation;
}

export async function installedControlOrigin(): Promise<string | null> {
  const invoke = nativeInvoke();
  if (!invoke) return null;
  const value = object(await invokeControl(invoke, { action: "config" }));
  if (value.ok !== true || value.configured !== true || typeof value.origin !== "string") throw new Error("本机安全控制组件未配置，请更新完整桌面组件");
  return value.origin;
}

export async function settingsRequest(origin: string, path: string, token: string, body?: unknown): Promise<Record<string, unknown>> {
  origin = controlOrigin(origin);
  if (path !== "" && path !== "/apply") throw new Error("不支持的配置操作");
  const invoke = nativeInvoke();
  let value: Record<string, unknown>;
  let status: unknown;
  if (invoke) {
    value = object(await invokeControl(invoke, { action: path ? "apply" : "get", origin, body: body ?? null }));
    status = value.status;
  } else {
    if (!token) throw new Error("请先填写控制授权");
    const response = await fetchWithTimeout(`${origin}/api/collection/settings${path}`, {
      method: body === undefined ? "GET" : "POST", redirect: "error", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-FAPAI-Control-Token": token },
      body: body === undefined ? undefined : JSON.stringify(body),
    }, CONTROL_TIMEOUT_MS);
    status = response.status;
    value = response.ok ? object(await response.json()) : { ok: false };
  }
  if (status === 404) throw new Error("线上尚未启用采集配置接口；本机草稿未应用到 PC2");
  if (value.ok !== true) throw new Error(status ? `控制接口未完成请求（HTTP ${status}）；请刷新状态，不要重复提交` : "安全控制连接失败；请检查证书、凭据和控制地址，不要重复提交");
  return value;
}

export async function installedRestartRequest(origin: string, requestId?: string): Promise<Record<string, unknown>> {
  const invoke = nativeInvoke();
  if (!invoke) throw new Error("本机安全控制组件不可用");
  const value = object(await invokeControl(invoke, {
    action: requestId ? "restart" : "restart_status", origin: controlOrigin(origin),
    body: requestId ? { request_id: requestId } : null,
  }));
  if (value.ok !== true) throw new Error("PC2 重启控制连接失败，请刷新状态确认");
  return value;
}

export async function installedRuntimeRequest(origin: string, action: string): Promise<Record<string, unknown>> {
  if (!["start", "pause", "resume"].includes(action)) throw new Error("Unsupported runtime action");
  const invoke = nativeInvoke();
  if (!invoke) throw new Error("Native control transport unavailable");
  const value = object(await invokeControl(invoke, { action, origin: controlOrigin(origin), body: {} }));
  if (value.ok !== true) throw new Error("Runtime operation was not confirmed; refresh the current state");
  return value;
}

const collectionActions: Readonly<Record<string, string>> = {
  "/api/collection/item/manual_update": "manual_update",
  "/api/collection/item/reanalyze": "reanalyze",
  "/api/collection/region/reset_links": "reset_links",
};

export async function collectionWriteRequest(base: string, path: string, body: unknown, token = ""): Promise<Record<string, unknown>> {
  if (!Object.hasOwn(collectionActions, path)) throw new Error("Unsupported collection write action");
  const action = collectionActions[path];
  const invoke = nativeInvoke();
  let value: Record<string, unknown>;
  if (invoke) {
    const origin = await installedControlOrigin();
    if (!origin) throw new Error("Native control transport unavailable");
    value = object(await invokeControl(invoke, { action, origin, body }));
  } else {
    const origin = controlOrigin(base);
    if (!token) throw new Error("请先填写控制授权");
    const response = await fetchWithTimeout(`${origin}${path}`, {
      method: "POST", redirect: "error", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-FAPAI-Control-Token": token },
      body: JSON.stringify(body),
    }, CONTROL_TIMEOUT_MS);
    if (!response.ok) throw new Error(`Collection write rejected (HTTP ${response.status})`);
    value = object(await response.json());
  }
  if (value.ok !== true) throw new Error("Collection write was not confirmed; refresh before retrying");
  return value;
}
