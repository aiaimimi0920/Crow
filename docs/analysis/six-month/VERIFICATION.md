# Verification receipt — 2026-11-18

Scope: offline Crow analysis prototype only. Base HEAD 1f373c6ab93fbc737e3342f655985d6246c81ea2.
New paths: src/analysis/, tests/analysis/, docs/analysis/six-month/.
Existing user untracked backup files preserved. No commit, push, deployment or service restart.

- Final focused regression: 17 passed (0.46s).
- Ruff check passed; Ruff formatting applied only new analysis/test files.
- Python compileall passed on src/analysis.
- Effective-code-lines checker unit tests: 19 passed.
- Effective-code-lines ratchet: passed (1852 files; none >500 effective lines), final 17-test code state; final-v3 report recorded in artifacts/analysis.
- Independent read-only review ran prior 16-test state successfully, poisoned holdout resale values without changing Crow-only predictions, verified 80 collector/storage/server/dependency file hashes unchanged. No blocking offline-prototype findings. Added 17th test only validates preflight does not consume holdout receipt.
- Final demo command succeeded: 1728 synthetic transactions, eight cities, both Crow-only and market-augmented temporal validation and cross-city inference; each run trained 8 examples and predicted 4. This is plumbing evidence only, NOT real accuracy.
- Real Crow aggregation succeeded: 10467 auction community-month cells. These are not ordinary resale labels, verified residential property counts or real forecasts.
- Collector/storage/server/requirements tracked hashes match pre-work capture. git diff --name-only empty for pre-existing tracked source.

Artifacts (local, ignored runtime outputs):
artifacts/analysis/crow-community-month-v1.json
artifacts/analysis/synthetic-e2e-final.json
artifacts/analysis/collector-before.sha256
artifacts/analysis/effective-code-lines-final-v3.json

Not run: full historical collection/security/desktop/production suites (no shared runtime changes); LightGBM/CatBoost execution (not installed); real supervised training or accuracy scoring (ordinary resale ground truth not connected); final real holdout remains untouched.


## Second slice: standalone trained artifact and inference

- Added persistence.py/inference.py, CLI train/predict, and dedicated tests.
- Final suite: 28 tests passed in 0.53s; Ruff check/format, compileall, effective-line ratchet passed (1855 files).
- Separate processes trained synthetic ridge artifact, loaded JSON, and predicted 2 synthetic community results with no ordinary resale input.
- JSON model validates schema, dimensions, finite values, feature order, allowed training cities, source mode and synthetic status. No pickle.
- Synthetic artifact applied to real Crow data is refused. Real model training without mature ordinary resale target is refused.
- Collector hashes rechecked unchanged; no deployment/restart/commit/push.
- Artifact reports: standalone-synthetic-model-v1.json / standalone-synthetic-predictions-v1.json / effective-code-lines-inference-v1.json under artifacts/analysis.
- Independent review found finite coefficients could underflow exp to zero price. Fixed: reject non-positive as well as non-finite outputs; regression added. Final focused suite: 29 passed. Final effective-line report: effective-code-lines-inference-final.json. Standalone CLI predict rerun after fix succeeded using synthetic inputs only.

## Current-input boundary slice

37 tests passed (1.28s). Real current-input CLI on 2026-11-18 returned refused_no_recent_crow_history, latest usable auction 2026-02-28, zero candidate features and no market predictions. Raw bytes read only; identity and historical-availability limitations explicit. Added regression for stale inputs, no fabricated output and non-finite/zero derived archive prices.


## Worker-final slice, 2026-11-18
- Focused suite: 41 passed; independent reviewer reran all 41 (1.30s), no blocker for preview scope. Ruff check/format and effective-line ratchet passed.
- PC2 source reader ran in memory only, no collector-side code/data changes or deployment.
- Exact read samples under /srv/data/fapaifang-worker/output/nodes/pc2:
  - detail_analysis_worker_2/1073283224103/final.json: traded 2026-08-21 10:00:07, SHA256 dc4a6352a4faa2950f5153802668a15ea8c56692b164d21c41bb79e39d337302.
  - detail_analysis_worker_4/1073714800502/final.json: traded 2026-08-22 10:00:00, SHA256 9f6114a69329e0053d20badd1843a3da73215dbda7d48880179cb1e57bf0c7d6.
- Both processed=true, city Beijing; raw community/locality not certified. First sample address has commercial-building wording despite missing explicit property type: no residential claim.
- Existing NAS Windows path verified: \\192.168.15.200\home\project\project\FPFData\output\detail_worker\1034238044172\final.json. Actual CLI outputs nas-worker-final-single-v1.json / nas-current-single-v1.json in artifacts/analysis. Single sample outside eight-city split, so no usable aggregates or predictions.
- PC2 legacy-nas mounts the same existing NAS read-only. PC2 current output is on local ext4, not that mount. No current-output automatic NAS synchronization confirmed; no new access/service permissions created.
- No ordinary-truth training or final holdout score run in this slice. No claim of accuracy, residential certification, historical availability, or cross-file atomic snapshot.


## Explicit temporal contract / fold manifest (2026-11-18)
- Added temporal.py validation at direct fit/backtest entrypoints: no duplicate group/origin weighting, fixed six-calendar-month target, positive finite baseline/label, labels unavailable before the complete target month closes.
- Each successful or insufficient-data fold now reports training cities, latest training origin and label availability, fit cutoff, row counts and deterministic membership SHA256. The hash covers group/origin/target-month identity only, not data values or model bytes; it is audit information, not tamper protection or a substitute for source hashes.
- Six added synthetic regression cases; 47 tests pass. Ruff import fixes applied, effective-line ratchet passes (1863 files), collector boundary remains 80/80 unchanged.
- CLI demo actually ran to artifacts/analysis/synthetic-temporal-manifest-v1.json. Both input modes and temporal/holdout branches remain explicitly synthetic. This is not a new real-data backtest or evidence of predictive accuracy.


## Price semantics and Beijing calendar (2026-11-18)
- Read-only contract blob verified: 2eea120f7033cacf4ce2baacb932feae6ec0ba25. transaction_price is hammer/auction transaction yuan; actual_paid_price is an optional estimated total including taxes/arrears. Analysis uses only the former/legacy 成交价格, never substitutes estimated costs. Collector comments about training labels do not redefine Crow's ordinary resale target.
- Existing NAS final sample 1034238044172 has equal nested/legacy transaction price 2465349, cost estimate null, date string 2026-04-22 04:57:12, explicit sold true. Missing area yields no unit price. This field check does not independently certify sale settlement or actual timestamp timezone provenance.
- Fixed parse_date: explicit Z/UTC offsets convert to UTC+08 before day/month selection; naive collector timestamps retain their Beijing calendar date per contract. Date-only and slash dates remain accepted. No host timezone inference or timestamp/availability fabrication.
- Added 5 calendar boundaries (Z crosses month, +08 equivalent, +09 reverse cross-month, naive, date-only) and cost-estimate exclusion regression. 53 focused tests pass. Only analysis contract/tests/docs changed; collector remains read-only.


## Nested final compatibility (2026-11-18)
- Reader now accepts audit.is_processed when flat is_processed is absent; all supplied non-null completion flags must be true. A false/conflicting alias never certifies completion.
- Item identity supports nested source.item_id / source.source_item_id. Storage ID and platform ID are separate namespaces; conflicts within the same namespace fail closed rather than selecting arbitrary aliases. Neither is promoted to physical-asset identity. Numeric worker directory must still match selected storage/fallback item ID.
- Four new synthetic schema regressions, total 57 passed; actual existing NAS completed final 1034238044172 decoded successfully again without creating output or changing source. sold remains based on explicit original flag, not schema status done; property_id/available_at remain unknown.
- Ruff passes; all 80 collector boundary hashes unchanged. No new true ordinary labels, trained real model, or real prediction accuracy obtained. This closes an ingestion compatibility gap, not the remaining empirical validation gap.

- Independent review found and reproduced an ID namespace collision in the initial nested adapter. Fixed by separating raw worker-directory ID from namespace-qualified analysis dedup keys: [storage,id] versus [platform,platform-name-or-unknown,id], serialized unambiguously as JSON. Explicit flat/nested same-namespace aliases remain compatible. No speculative cross-namespace entity matching is performed; unknown platform is still unverified.
- Regression covers unrelated storage 123/source 999 versus platform-only 123: same-price same-cell rows remain two observations rather than merging. Total 59 tests now pass; earlier 57-test snapshot was not final acceptance.


## Multi-origin rolling acceptance (2026-11-18)
- Demo now runs three training-city temporal origins (2023-02-28 / 04-30 / 07-31) and one separately frozen synthetic holdout origin. Each fit selects only labels mature by its own cutoff. No actual heldout data or real fit used.
- rolling_summary provides same-row paired MAE differences, equal-fold mean difference, unavailable-label prediction counts and insufficient-data folds. Negative difference favors the model; these are descriptive, dependent observations, not statistical significance or national generalization. Coverage denominator is generated predictions only, never all communities. Crow-only comparison is calibration versus model, not with/without-auction evidence.
- Three added tests (unequal fold sizes, no-score nulls, multi-origin maturation). 62 focused tests pass. CLI output: artifacts/analysis/synthetic-multi-origin-v1.json, explicitly synthetic; each input mode has 3 temporal folds / 12 scored synthetic predictions. Does not provide real accuracy.
