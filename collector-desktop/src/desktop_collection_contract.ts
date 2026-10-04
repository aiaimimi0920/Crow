import { object } from "./desktop_value.ts";

export type CollectionStage = "links" | "details" | "analysis";
export type CollectionRecord = Record<string, unknown>;
export type RefreshOptions = { silent?: boolean };

export interface CollectionRegion {
  location_code: string;
  province: string;
  city: string;
  district: string;
  label: string;
  status_label: string;
  completed: boolean;
  counts?: CollectionRecord;
}

export interface RegionCity {
  name: string;
  province: string;
  regions: CollectionRegion[];
  districts: (CollectionRegion & { displayDistrict: string })[];
}

export interface RegionProvince {
  name: string;
  regions: CollectionRegion[];
  cities: RegionCity[];
}

export function recordArray(value: unknown): CollectionRecord[] {
  return Array.isArray(value) ? value.map(object) : [];
}

export function collectionRegions(value: unknown): CollectionRegion[] {
  return recordArray(value).map((row) => ({
    location_code: String(row.location_code ?? ""),
    province: String(row.province ?? ""),
    city: String(row.city ?? ""),
    district: String(row.district ?? ""),
    label: String(row.label ?? ""),
    status_label: String(row.status_label ?? ""),
    completed: row.completed === true,
    counts: object(row.counts),
  }));
}

export function isCollectionStage(value: unknown): value is CollectionStage {
  return value === "links" || value === "details" || value === "analysis";
}
