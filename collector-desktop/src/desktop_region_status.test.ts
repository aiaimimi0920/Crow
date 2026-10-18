import assert from "node:assert/strict";
import test from "node:test";
import { collectionRegions } from "./desktop_collection_contract.ts";
import { aggregateRegionStatus, displayRegion } from "./desktop_region_status.ts";

test("completed plus queued districts are waiting, not running", () => {
  const regions = collectionRegions([{ completed: true }, { status_label: "待采集" }]);
  assert.equal(aggregateRegionStatus(regions).status_label, "待继续");
  assert.equal(aggregateRegionStatus(collectionRegions([{ status_label: "待采集" }])).status_label, "待采集");
});

test("only execution labels produce a live badge; completion requires every district", () => {
  for (const label of ["待继续", "等待重试", "等待链接", "存在失败/阻塞", "已暂停"]) {
    const result = aggregateRegionStatus(collectionRegions([{ status_label: label }]));
    assert.equal(result.status_label, label);
    assert.notEqual(result.className, "live");
  }
  assert.equal(aggregateRegionStatus(collectionRegions([{ status_label: "采集中" }])).className, "live");
  assert.equal(aggregateRegionStatus(collectionRegions([{ completed: true }])).status_label, "本轮完成");
});

test("paused or unleased work is not shown as executing and selection data is untouched", () => {
  const [region] = collectionRegions([{ location_code: "371602", status_label: "采集中", counts: { active_progress: 0 } }]);
  assert.equal(displayRegion(region, true).status_label, "已暂停");
  assert.equal(displayRegion(region, false).status_label, "待继续");
  assert.equal(region.status_label, "采集中");
  assert.equal(displayRegion(region, true).location_code, "371602");
});
