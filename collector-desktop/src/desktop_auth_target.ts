export const DEFAULT_AUTH_CHALLENGE_URL = "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1";

export function authTargetScope(value: unknown): "seed" | "detail" | null {
  let parsed: URL;
  try { parsed = new URL(String(value || "")); }
  catch { return null; }
  if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password || (parsed.port && parsed.port !== "443")) return null;
  const path = parsed.pathname.replace(/\/{2,}/g, "/").split("/_____tmd_____/punish", 1)[0];
  if (parsed.hostname === "sf-item.taobao.com" && /^\/sf_item\/\d+\.htm$/.test(path)) return "detail";
  if (parsed.hostname === "sf.taobao.com" && path.startsWith("/list/")) return "seed";
  return null;
}

export function normalizeAuthChallengeUrl(value: unknown): string {
  let parsed: URL;
  try { parsed = new URL(String(value || "")); }
  catch { return DEFAULT_AUTH_CHALLENGE_URL; }
  if (!/^https?:$/.test(parsed.protocol) || parsed.username || parsed.password || (parsed.port && parsed.port !== "443")) return DEFAULT_AUTH_CHALLENGE_URL;
  const path = parsed.pathname.replace(/\/{2,}/g, "/").split("/_____tmd_____/punish", 1)[0];
  if (parsed.hostname === "sf-item.taobao.com" && /^\/sf_item\/\d+\.htm$/.test(path)) {
    return `https://sf-item.taobao.com${path}`;
  }
  if (parsed.hostname !== "sf.taobao.com" || !path.startsWith("/list/")) return DEFAULT_AUTH_CHALLENGE_URL;
  const target = new URL(`https://sf.taobao.com${path}`);
  // Retain the requested collection region, not transient challenge credentials.
  for (const key of ["location_code", "st_param", "auction_start_seg", "page"]) {
    const value = parsed.searchParams.get(key);
    if (value) target.searchParams.set(key, value);
  }
  target.searchParams.set("__captcha_solver_bg", "1");
  return target.toString();
}
