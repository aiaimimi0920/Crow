export const HOST = "com.crow.manual_auth";
export function nativeFailure(message) {
  const failures = {
    "Specified native messaging host not found.": "native_not_found",
    "Access to the specified native messaging host is forbidden.": "native_forbidden",
    "Failed to start native messaging host.": "native_start_failed",
    "Native host has exited.": "native_exited",
    "Error when communicating with the native messaging host.": "native_protocol_failed",
  };
  return Object.hasOwn(failures, message) ? failures[message] : "native_unavailable";
}
export const ORIGINS = ["https://sf.taobao.com/", "https://sf-item.taobao.com/",
  "https://susong-item.taobao.com/", "https://login.taobao.com/"];
const domains = new Set(["taobao.com", "sf.taobao.com", "sf-item.taobao.com", "susong-item.taobao.com", "login.taobao.com"]);

export function targetIdentity(value) {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password || (url.port && url.port !== "443")) throw new Error("invalid_target");
  if (!((url.hostname === "sf.taobao.com" && url.pathname.startsWith("/list/"))
    || (url.hostname === "sf-item.taobao.com" && /^\/sf_item\/\d+\.htm$/.test(url.pathname)))) throw new Error("invalid_target");
  url.hash = "";
  url.searchParams.delete("__captcha_solver_bg");
  url.searchParams.sort();
  return url.href;
}

export function selectCookies(groups) {
  const result = new Map();
  for (const cookie of groups.flat()) {
    if (!domains.has(cookie.domain.replace(/^\./, ""))) continue;
    if (cookie.partitionKey) throw new Error("edge_partition_unsupported");
    result.set(JSON.stringify([cookie.domain, cookie.path, cookie.name]), cookie);
  }
  if (!result.size || result.size > 500) throw new Error("invalid_snapshot");
  return [...result.values()];
}

export const messages = {
  native_not_found: "Edge 未找到或未能加载本机认证助手（native_not_found）。请检查助手注册、清单和启动文件；仅重装扩展不一定能解决。",
  native_version_mismatch: "本机助手版本不匹配，请更新 Crow 认证助手后重试（native_version_mismatch）。",
  native_forbidden: "Edge 拒绝此扩展访问本机助手（native_forbidden），请检查扩展 ID 和浏览器策略。",
  native_start_failed: "Edge 找到了注册项，但未能启动本机助手（native_start_failed）。",
  native_exited: "本机助手启动后提前退出（native_exited）。",
  native_protocol_failed: "Edge 与本机助手的消息通信失败（native_protocol_failed）。",
  edge_task_missing: "没有待处理任务。请先在 Crow 中点击 Edge 认证。",
  edge_task_expired: "任务已过期，请在 Crow 重新打开 Edge 认证。",
  edge_task_changed: "任务已更新，请重新连接 Crow。",
  edge_wrong_profile: "此 Edge 配置不是已配对配置，请使用首次配对的 Edge 配置。",
  edge_already_submitted: "已提交，请回 Crow 点击“已完成挑战”。",
  edge_partition_unsupported: "该会话含当前交接协议不支持的分区 Cookie，未提交。请使用专用浏览器入口。",
  challenge_page_not_ready: "认证页面未回到原目标，请完成登录并打开原目标后提交。",
};
