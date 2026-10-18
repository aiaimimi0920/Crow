import type { CollectionRegion } from "./desktop_collection_contract.ts";

export function aggregateRegionStatus(regions: CollectionRegion[]) {
  const result = (status_label: string, className = "warn", completed = false) => ({ completed, status_label, className });
  if (!regions.length) return result("待采集");
  if (regions.every((region) => region.completed)) return result("本轮完成", "ok", true);
  const labels = regions.filter((region) => !region.completed).map((region) => region.status_label);
  if (labels.includes("采集中")) return result("采集中", "live");
  if (labels.some((label) => /失败|阻塞/.test(label))) return result("存在失败/阻塞", "bad");
  if (labels.includes("等待重试")) return result("等待重试");
  if (labels.includes("已暂停")) return result("已暂停");
  if (labels.includes("待继续") || regions.some((region) => region.completed)) return result("待继续");
  if (labels.includes("等待链接")) return result("等待链接");
  return result("待采集");
}

export function displayRegion(region: CollectionRegion, paused: boolean): CollectionRegion {
  if (region.completed) return { ...region, status_label: "本轮完成" };
  if (paused && region.status_label === "采集中") return { ...region, status_label: "已暂停" };
  // Older servers cannot distinguish queued tasks from leased work.
  if (region.status_label === "采集中" && region.counts) {
    const active = region.counts.active_progress ?? region.counts.active_items;
    if (active === 0) return { ...region, status_label: "待继续" };
  }
  return region;
}
