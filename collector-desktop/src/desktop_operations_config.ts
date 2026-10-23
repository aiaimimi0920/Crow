import { object } from "./desktop_value.ts";
import { count, pair, renderReceipt } from "./desktop_operations_view.ts";

export function renderOperationsConfig(value: unknown, receivedAt = Date.now()): string {
  const data = object(value), effective = object(data.effective), workers = object(effective.workers), ai = object(effective.ai);
  const model = typeof ai.model === "string" && /^[a-zA-Z0-9._:/ -]{1,120}$/.test(ai.model) ? ai.model : "未上报";
  const efforts = ["none", "minimal", "low", "medium", "high", "xhigh"];
  const effort = efforts.includes(String(ai.reasoning_effort)) ? String(ai.reasoning_effort) : "未上报";
  return `<p class="status-line">最近读取 ${new Date(receivedAt).toLocaleString("zh-CN", { hour12: false })} · ${data.available === true ? "PC2 控制器在线" : "PC2 控制器离线 / 未上报"}；这是读取时的配置，不是实时模型可用性检测。</p>
    <dl class="ops-facts">${pair("配置请求版本", count(data.revision))}${pair("生效 Worker：链接 / 详情 / AI", [workers.links, workers.details, workers.analysis].map(count).join(" / "))}
    ${pair("生效 AI 模型", model)}${pair("GPT 使用许可", ai.allow_gpt === true ? "已开启" : ai.allow_gpt === false ? "已关闭" : "未上报")}${pair("推理强度", effort)}
    ${pair("AI 超时（秒）", count(ai.timeout_seconds))}${pair("AI 密钥", data.api_key_configured === true ? "已配置（不回显）" : data.api_key_configured === false ? "未配置" : "未知")}</dl>
    <p class="status-line">仅展示控制器上报的 effective 配置；本机草稿和尚未生效的 desired 配置不作为当前配置。请求版本不代表配置已生效。</p>
    <h3>最近配置操作</h3>${renderReceipt(data.request)}`;
}
