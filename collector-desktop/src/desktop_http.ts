import { READ_TIMEOUT_MS } from "./desktop_config.ts";
import { object } from "./desktop_value.ts";

let configurationBlocked = false;
export function isConfigurationBlocked(): boolean { return configurationBlocked; }
export function setConfigurationBlocked(blocked: boolean): void { configurationBlocked = blocked; }

export async function fetchWithTimeout(url: string, options: RequestInit = {}, timeoutMs = READ_TIMEOUT_MS): Promise<Response> {
  if (configurationBlocked) throw new Error("Crow API configuration conflict");
  const controller = new AbortController();
  let timedOut = false;
  const cancel = () => controller.abort(options.signal?.reason);
  options.signal?.addEventListener("abort", cancel, { once: true });
  if (options.signal?.aborted) cancel();
  const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (timedOut && error instanceof Error && error.name === "AbortError") {
      throw new Error(`请求超时（${Math.round(timeoutMs / 1000)} 秒）：${url}`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener("abort", cancel);
  }
}

export async function readJson(url: string, timeoutMs = READ_TIMEOUT_MS): Promise<Record<string, unknown>> {
  const response = await fetchWithTimeout(url, { cache: "no-store" }, timeoutMs);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return object(await response.json());
}
