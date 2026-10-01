import { object } from "./desktop_value.ts";
import { authTargetScope, DEFAULT_AUTH_CHALLENGE_URL, normalizeAuthChallengeUrl } from "./desktop_auth_target.ts";

export type AuthScope = "seed" | "detail";
export const scopeLabel = (scope: AuthScope): string => scope === "seed" ? "链接采集" : "详情采集";

export function authScopeState(value: unknown, scope: AuthScope): Record<string, unknown> | null {
  const status = object(object(value).status);
  const solver = object(status.captcha_solver);
  const scopes = object(status.collection_scopes || solver.scopes || solver.collection_scopes);
  return scopes[scope] && typeof scopes[scope] === "object" ? object(scopes[scope]) : null;
}

export function authScopeChallenge(value: unknown, scope: AuthScope): boolean | null {
  const selected = authScopeState(value, scope);
  if (!selected) return null;
  return Boolean(selected.manual_required || selected.force_reset_required || selected.node_solver_blocked
    || (selected.paused && selected.pause_reason !== "operator")
    || ["running", "queued", "manual_required"].includes(String(selected.last_status)));
}

export function authScopeTarget(value: unknown, scope: AuthScope, itemId: unknown = ""): string {
  const request = object(authScopeState(value, scope)?.last_request);
  const candidate = request.challenge_target_url || request.target_url || request.url;
  const normalized = candidate ? normalizeAuthChallengeUrl(candidate) : "";
  const targetScope = authTargetScope(normalized);
  if (scope === "seed") return targetScope === "seed" ? normalized : DEFAULT_AUTH_CHALLENGE_URL;
  if (targetScope === "detail") return normalized;
  return /^\d+$/.test(String(itemId)) ? `https://sf-item.taobao.com/sf_item/${itemId}.htm` : "";
}
