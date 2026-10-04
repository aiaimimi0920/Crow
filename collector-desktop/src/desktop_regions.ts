import { callAction } from "./desktop_actions.ts";
import { state } from "./desktop_state.ts";
import { $, fmt, formatRefreshTime, getJson, postJson, setRegionRefreshStatus, confirmRegionReset } from "./desktop_shared.ts";
import { escapeHtml as esc } from "./desktop_dom.ts";
import { errorMessage, object } from "./desktop_value.ts";
import { collectionRegions, type CollectionRecord, type CollectionRegion, type RefreshOptions, type RegionCity, type RegionProvince } from "./desktop_collection_contract.ts";
import { regionProgress } from "./desktop_region_progress.ts";

export function itemRegion(item: CollectionRecord): string {
  const payload = object(item.source_payload);
  const occurrence = object(item.latest_occurrence);
  const code =
    payload.list_location_code ||
    occurrence.location_code ||
    String(occurrence.job_key || item.first_seen_job_key || "").split("-")[0];
  const name = [payload.city, payload.district].filter(Boolean).join(" ");
  return String(name || payload.location || payload.full_address || (code ? `地区代码 ${code}` : "-"));
}

export function collectionStatusLabel(item: CollectionRecord): string {
  if (item.status === "detail_completed") {
    return "AI 已分析";
  }
  if (["raw_detail_captured", "analysis_in_progress", "analysis_failed", "analysis_blocked"].includes(String(item.status))) {
    return "详情已采集";
  }
  return "链接已采集";
}

export function regionStatusClass(region: CollectionRegion): string {
  const label = String((region && region.status_label) || "");
  if (region && region.completed) {
    return "ok";
  }
  if (label.includes("失败") || label.includes("阻塞")) {
    return "bad";
  }
  return "warn";
}

export function regionPart(value: unknown, fallback: string): string {
  const text = String(value || "").trim();
  return text || fallback;
}

export function buildRegionTree(regions: CollectionRegion[]): RegionProvince[] {
  const provinceMap = new Map<string, { name: string; regions: CollectionRegion[]; cityMap: Map<string, RegionCity> }>();
  for (const region of regions || []) {
    const provinceName = regionPart(region.province, "未知省份");
    const cityName = regionPart(region.city, "未知城市");
    const districtName = regionPart(region.district || region.label || region.location_code, "未知地区");
    let province = provinceMap.get(provinceName);
    if (!province) {
      province = { name: provinceName, regions: [], cityMap: new Map() };
      provinceMap.set(provinceName, province);
    }
    province.regions.push(region);
    let city = province.cityMap.get(cityName);
    if (!city) {
      city = { name: cityName, province: provinceName, regions: [], districts: [] };
      province.cityMap.set(cityName, city);
    }
    city.regions.push(region);
    city.districts.push({ ...region, displayDistrict: districtName });
  }
  return Array.from(provinceMap.values()).map((province) => ({
    name: province.name,
    regions: province.regions,
    cities: Array.from(province.cityMap.values()),
  }));
}

export function aggregateRegionStatus(regions: CollectionRegion[]) {
  const scopedRegions = regions || [];
  if (!scopedRegions.length) {
    return { completed: false, status_label: "待采集", className: "warn" };
  }
  if (scopedRegions.every((region) => region.completed)) {
    return { completed: true, status_label: "收集完成", className: "ok" };
  }
  const hasProblem = scopedRegions.some((region) => {
    const label = String(region.status_label || "");
    return label.includes("失败") || label.includes("阻塞");
  });
  if (hasProblem) {
    return { completed: false, status_label: "存在失败/阻塞", className: "bad" };
  }
  if (scopedRegions.every((region) => region.status_label === "待采集")) {
    return { completed: false, status_label: "待采集", className: "warn" };
  }
  return { completed: false, status_label: "采集中", className: "warn" };
}

export function regionStatusBadge(status: { className?: string; status_label: string }): string {
  return `<span class="region-status ${esc(status.className || "warn")}">${fmt(status.status_label)}</span>`;
}

export function validateRegionSelection(regionTree: RegionProvince[]): void {
  const regions = state.regions || [];
  const selectedRegion = regions.find((region) => region.location_code === state.selectedLocationCode);
  if (state.selectedLocationCode && !selectedRegion) {
    state.selectedLocationCode = "";
  }
  if (selectedRegion) {
    state.selectedProvince = regionPart(selectedRegion.province, "未知省份");
    state.selectedCity = regionPart(selectedRegion.city, "未知城市");
    return;
  }
  const province = regionTree.find((candidate) => candidate.name === state.selectedProvince);
  if (!province) {
    state.selectedProvince = "";
    state.selectedCity = "";
    return;
  }
  const city = province.cities.find((candidate) => candidate.name === state.selectedCity);
  if (state.selectedCity && !city) {
    state.selectedCity = "";
  }
}

export function selectedProvinceNode(regionTree: RegionProvince[]): RegionProvince | null {
  return regionTree.find((province) => province.name === state.selectedProvince) || null;
}

export function selectedCityNode(province: RegionProvince | null): RegionCity | null {
  if (!province) {
    return null;
  }
  return province.cities.find((city) => city.name === state.selectedCity) || null;
}

export function renderProvinceTabs(regionTree: RegionProvince[]): void {
  const allActive = state.selectedProvince ? "" : "active";
  const allStatus = aggregateRegionStatus(state.regions || []);
  const chips = [
    `<button class="region-tab province-tab ${allActive}" data-province="">全部省份${regionStatusBadge(allStatus)}</button>`,
    ...regionTree.map((province) => {
      const active = province.name === state.selectedProvince ? "active" : "";
      const status = aggregateRegionStatus(province.regions);
      const completed = status.completed ? "completed" : "";
      return `<button class="region-tab province-tab ${active} ${completed}" data-province="${esc(province.name)}">
        <span>${fmt(province.name)}</span>${regionStatusBadge(status)}
      </button>`;
    }),
  ];
  $("provinceTabs").innerHTML = chips.join("");
  document.querySelectorAll<HTMLButtonElement>(".province-tab").forEach((button) =>
    button.addEventListener("click", async () => {
      state.selectedProvince = button.dataset.province || "";
      state.selectedCity = "";
      state.selectedLocationCode = "";
      state.offset = 0;
      callAction("hideDetailPanel");
      renderRegionSelectors();
      await callAction("loadItems");
    }),
  );
}

export function renderCityTabs(province: RegionProvince | null): void {
  if (!state.selectedProvince || !province) {
    $("cityTabs").innerHTML = '<span class="status-line">请先选择省份</span>';
    return;
  }
  const allActive = state.selectedCity ? "" : "active";
  const allStatus = aggregateRegionStatus(province.regions);
  const chips = [
    `<button class="region-tab city-tab ${allActive}" data-city="">全部城市${regionStatusBadge(allStatus)}</button>`,
    ...province.cities.map((city) => {
      const active = city.name === state.selectedCity ? "active" : "";
      const status = aggregateRegionStatus(city.regions);
      const completed = status.completed ? "completed" : "";
      return `<button class="region-tab city-tab ${active} ${completed}" data-city="${esc(city.name)}">
        <span>${fmt(city.name)}</span>${regionStatusBadge(status)}
      </button>`;
    }),
  ];
  $("cityTabs").innerHTML = chips.join("");
  document.querySelectorAll<HTMLButtonElement>(".city-tab").forEach((button) =>
    button.addEventListener("click", async () => {
      state.selectedCity = button.dataset.city || "";
      state.selectedLocationCode = "";
      state.offset = 0;
      callAction("hideDetailPanel");
      renderRegionSelectors();
      await callAction("loadItems");
    }),
  );
}

export function renderDistrictTabs(city: RegionCity | null): void {
  if (!state.selectedProvince) {
    $("districtTabs").innerHTML = '<span class="status-line">请先选择省份</span>';
    return;
  }
  if (!state.selectedCity || !city) {
    $("districtTabs").innerHTML = '<span class="status-line">请先选择城市</span>';
    return;
  }
  const allActive = state.selectedLocationCode ? "" : "active";
  const allStatus = aggregateRegionStatus(city.regions);
  const chips = [
    `<button class="region-tab district-tab ${allActive}" data-location-code="">全部地区${regionStatusBadge(allStatus)}</button>`,
    ...city.districts.map((region) => {
      const active = region.location_code === state.selectedLocationCode ? "active" : "";
      const completed = region.completed ? "completed" : "";
      const badgeClass = regionStatusClass(region);
      const progress = regionProgress(region);
      return `<button class="region-tab district-tab ${active} ${completed}" data-location-code="${esc(region.location_code)}">
        <span>${fmt(region.displayDistrict || region.label || region.location_code)}</span>
        <span class="region-status ${badgeClass}" title="${esc(progress.hint)}">${fmt(region.status_label || "采集中")}${esc(progress.label)}</span>
      </button>`;
    }),
  ];
  $("districtTabs").innerHTML = chips.join("");
  document.querySelectorAll<HTMLButtonElement>(".district-tab").forEach((button) =>
    button.addEventListener("click", async () => {
      state.selectedLocationCode = button.dataset.locationCode || "";
      state.offset = 0;
      callAction("hideDetailPanel");
      renderRegionSelectors();
      await callAction("loadItems");
    }),
  );
}

export function renderRegionSelectors() {
  const regionTree = buildRegionTree(state.regions || []);
  validateRegionSelection(regionTree);
  const province = selectedProvinceNode(regionTree);
  const city = selectedCityNode(province);
  const district = (state.regions || []).find((region) => region.location_code === state.selectedLocationCode);
  $("regionSelection").textContent = [state.selectedProvince, state.selectedCity, district?.district || district?.label]
    .filter(Boolean).join(" / ") || "全部地区";
  if (state.selectedProvince && !state.selectedLocationCode) {
    $("regionSelection").textContent += "（选定区县后筛选商品）";
  }
  renderProvinceTabs(regionTree);
  renderCityTabs(province);
  renderDistrictTabs(city);
  document.querySelectorAll(".region-tab").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.classList.contains("active")));
  });
  if (state.stage === "links" && state.selectedLocationCode) {
    $("resetRegionLinks").classList.remove("hidden");
  } else {
    $("resetRegionLinks").classList.add("hidden");
  }
}

export async function loadRegions(options: RefreshOptions = {}): Promise<void> {
  const silent = Boolean(options && options.silent);
  const requestId = ++state.regionsRequestId;
  const stage = state.stage;
  const apiBase = state.apiBase;
  const current = () => requestId === state.regionsRequestId && stage === state.stage && apiBase === state.apiBase;
  if (!silent) {
    setRegionRefreshStatus("所在地刷新中...");
  }
  if (!silent || !(state.regions || []).length) {
    $("provinceTabs").innerHTML = '<span class="status-line">所在地加载中...</span>';
    $("cityTabs").innerHTML = "";
    $("districtTabs").innerHTML = "";
  }
  try {
    const payload = await getJson(`/api/collection/regions?stage=${encodeURIComponent(stage)}`);
    if (!current()) return;
    state.regions = collectionRegions(payload.regions);
    renderRegionSelectors();
    state.lastRegionRefreshAt = new Date();
    setRegionRefreshStatus(`最后刷新所在地 ${formatRefreshTime(state.lastRegionRefreshAt)}；每 10 分钟自动刷新所在地状态`);
  } catch (error) {
    if (!current()) return;
    $("regionSelection").textContent = state.regions.length ? "地区状态已过期，请展开筛选重试" : "地区读取失败，请展开筛选重试";
    setRegionRefreshStatus(`所在地刷新失败；每 10 分钟自动重试：${errorMessage(error)}`);
    if (!(state.regions || []).length) {
      $("provinceTabs").innerHTML = `<span class="error">所在地加载失败：${esc(errorMessage(error))}</span>`;
    }
  }
}

export async function resetSelectedRegionLinks() {
  if (state.stage !== "links" || !state.selectedLocationCode) {
    return;
  }
  const selected = (state.regions || []).find((region) => region.location_code === state.selectedLocationCode);
  const label = (selected && selected.label) || state.selectedLocationCode;
  const locationCode = state.selectedLocationCode;
  const apiBase = state.apiBase;
  const confirmed = await confirmRegionReset(`确定要重置“${label}”的商品链接采集状态吗？已有商品、详情页文本和 AI 分析数据会保留，但该地区链接会从第一页重新扫描。`);
  if (!confirmed || state.stage !== "links" || state.selectedLocationCode !== locationCode || state.apiBase !== apiBase) {
    return;
  }
  $("listStatus").textContent = `正在重置 ${label} 的链接采集状态...`;
  try {
    await postJson("/api/collection/region/reset_links", {
      location_code: locationCode,
    });
    state.offset = 0;
    await callAction("loadOverview");
    await loadRegions();
    await callAction("loadItems");
  } catch (error) {
    $("listStatus").innerHTML = `<span class="error">重置失败：${esc(errorMessage(error))}</span>`;
  }
}
