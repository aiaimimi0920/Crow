import type { CollectionRegion } from "./desktop_collection_contract.ts";

export function regionProgress(region: CollectionRegion): { label: string; hint: string } {
  const counts = region.counts || {};
  const count = (key: string): number | null => {
    const value = counts[key];
    return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
  };
  const total = count("total_progress");
  const done = count("exhausted_progress");
  if (total === null || done === null || total === 0 || done > total) return { label: "", hint: "" };
  const parts = [`链接扫描子任务完成 ${done}/${total}（各分类、各排序分别扫描）`];
  for (const [key, name] of [["pending_progress", "待处理"], ["in_progress_progress", "正在执行"], ["blocked_progress", "阻塞"]]) {
    const value = count(key);
    if (value !== null) parts.push(`${name} ${value}`);
  }
  return { label: ` ${done}/${total}`, hint: parts.join("；") };
}
