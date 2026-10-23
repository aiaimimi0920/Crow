export type Config = Record<string, Record<string, number | string | boolean>>;
export const groups = [
  { key: "workers", label: "Worker 数量", fields: [["links", "链接", 1, 2], ["details", "详情", 1, 8], ["analysis", "AI 归档", 1, 8]] },
  { key: "intervals", label: "采集间隔（秒）", fields: [
    ["links", "链接 · 活跃批次", 1, 3600], ["links_idle", "链接 · 空闲轮询", 1, 3600],
    ["details", "详情 · 活跃批次", 1, 3600], ["details_idle", "详情 · 空闲轮询", 1, 3600],
    ["analysis", "AI · 活跃批次", 1, 3600], ["analysis_idle", "AI · 空闲轮询", 1, 3600],
    ["success_delay", "详情 · 单条成功后", 0, 300], ["failure_delay", "详情 · 单条失败后", 1, 3600],
  ] },
  { key: "retries", label: "尝试上限", fields: [
    ["detail_item_attempts", "单个详情", 1, 20], ["analysis_item_attempts", "单个分析任务", 1, 20],
    ["detail_batch_attempts", "详情批次", 1, 200], ["analysis_batch_attempts", "分析批次", 1, 200],
    ["ai_attempts", "AI 请求重试", 0, 10],
  ] },
  { key: "ai", label: "AI 连接", fields: [["base_url", "Base URL"], ["model", "模型路由"], ["timeout_seconds", "请求超时（秒）", 5, 600]] },
] as const;

export function controlOrigin(value: string): string {
  const url = new URL(value);
  if (url.username || url.password || url.search || url.hash || !["/", "/api", "/api/"].includes(url.pathname)) throw new Error("控制地址必须是无凭据的 API 根地址");
  if (url.protocol !== "https:" && !(url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname))) throw new Error("配置和密钥需要 HTTPS 或受保护的本机隧道，不能经远程明文 HTTP 发送");
  return url.origin;
}

export function readConfig(read: (id: string) => string): Config {
  const result: Config = {};
  for (const group of groups) {
    const values: Record<string, number | string> = {};
    for (const field of group.fields) {
      const raw = read(`${group.key}.${field[0]}`).trim();
      if (!raw) throw new Error(`请填写${field[1]}`);
      const number = Number(raw);
      if (field.length === 4) {
        const fractional = field[0] === "success_delay" || field[0] === "failure_delay";
        if (!Number.isFinite(number) || (!fractional && !Number.isInteger(number)) || number < field[2] || number > field[3]) throw new Error(`${field[1]}超出允许范围`);
        values[field[0]] = number;
      } else values[field[0]] = raw;
    }
    result[group.key] = values;
  }
  if (Object.values(result.workers).reduce<number>((sum, value) => sum + Number(value), 0) > 16) throw new Error("Worker 总数不能超过 16");
  let aiUrl: URL;
  try { aiUrl = new URL(String(result.ai.base_url)); } catch { throw new Error("AI 地址必须是 HTTP 或 HTTPS URL"); }
  if (!["http:", "https:"].includes(aiUrl.protocol) || aiUrl.username || aiUrl.password || aiUrl.search || aiUrl.hash) throw new Error("AI 地址不能包含凭据、查询参数或片段；密钥请填入独立输入框");
  const allow = read("ai.allow_gpt") ?? "";
  if (!["", "false", "true"].includes(allow)) throw new Error("GPT 开关必须为布尔值");
  if (allow === "true") result.ai.allow_gpt = true;
  const effort = read("ai.reasoning_effort") || "none";
  if (!["none", "minimal", "low", "medium", "high", "xhigh"].includes(effort)) throw new Error("不支持的推理强度");
  if (effort !== "none") result.ai.reasoning_effort = effort;
  const model = String(result.ai.model);
  if (!result.ai.allow_gpt && (/gpt|codex/i.test(model) || /(?:^|[/:._-])o\d+(?:[/:._-]|$)/i.test(model))) throw new Error("请先开启允许使用 GPT；关闭时请改用非 GPT 模型");
  return result;
}
