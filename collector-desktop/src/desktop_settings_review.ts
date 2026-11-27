import { groups, type Config } from "./desktop_settings_contract.ts";
import { object } from "./desktop_value.ts";

export function settingsChanges(effective: Config, edited: Config): string {
  const lines: string[] = [];
  const compare = (group: string, name: string, label: string, fallback?: string | boolean) => {
    const before = effective[group][name] ?? fallback;
    const after = edited[group][name] ?? fallback;
    if (before !== after) lines.push(`${label}: ${String(before)} → ${String(after)}`);
  };
  for (const group of groups) for (const field of group.fields) compare(group.key, field[0], `${group.label} · ${field[1]}`);
  compare("ai", "allow_gpt", "允许使用 GPT", false);
  compare("ai", "reasoning_effort", "推理强度", "none");
  if (lines.length > 0 && !edited.ai.allow_gpt && /gpt/i.test(String(edited.ai.model ?? ""))) {
    lines.push("注意：GPT 许可关闭时，首选 GPT 路由不会发送请求，仅使用已配置的非 GPT 后备候选。");
  }
  return lines.join("\n");
}

export function settingsStateSummary(value: Record<string, unknown>): string {
  const receipt = object(value.request);
  const labels: Record<string, string> = {
    requested: "已提交，等待 PC2 应用", applying: "PC2 正在应用配置",
    succeeded: "应用成功，容器健康检查通过（不代表 AI 推理成功）",
    failed: "应用失败，编辑内容未生效", expired: "请求已过期，未被 PC2 领取",
    unknown: "应用结果未确认，需检查 PC2，不能继续提交",
  };
  const result = receipt.status ? ` · 最近操作（版本 ${receipt.revision ?? "未知"}）：${labels[String(receipt.status)] || "未知状态"}` : "";
  return `${value.available ? "PC2 控制器在线" : "PC2 控制器离线"} · 当前配置版本 ${value.revision ?? "未知"}${result}`;
}
