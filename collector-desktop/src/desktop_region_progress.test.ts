import assert from "node:assert/strict";
import test from "node:test";
import { collectionRegions } from "./desktop_collection_contract.ts";
import { regionProgress } from "./desktop_region_progress.ts";

test("滨城显示 9/12 扫描进度，不把已采集商品数当作完成依据", () => {
  const [region] = collectionRegions([{ location_code: "371602", completed: false, counts: {
    total_jobs: 2, completed_jobs: 1, total_progress: 12, exhausted_progress: 9,
    pending_progress: 3, in_progress_progress: 0, blocked_progress: 0,
  } }]);
  assert.equal(region.completed, false);
  assert.equal(regionProgress(region).label, " 9/12");
  assert.match(regionProgress(region).hint, /待处理 3/);
});

test("旧 API 或无效计数不显示伪造进度", () => {
  for (const counts of [undefined, {}, { total_progress: 0, exhausted_progress: 0 },
    { total_progress: 1, exhausted_progress: 2 }, { total_progress: "12", exhausted_progress: 9 }]) {
    const [region] = collectionRegions([{ counts }]);
    assert.deepEqual(regionProgress(region), { label: "", hint: "" });
  }
});
