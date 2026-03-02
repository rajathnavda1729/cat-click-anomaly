# Log Anomaly Detection v2.0 — Execution Plan (Upgrade)

This document defines the **execution plan** for upgrading the cat-click-anomaly POC to the v2.0 design in [Log Anomaly Detection Upgrade Plan.md](./Log%20Anomaly%20Detection%20Upgrade%20Plan.md): seasonality, surge resilience, and semantic (text) features.

---

## 1. Execution Plan Overview

| Phase | Goal | Deliverables |
|-------|------|--------------|
| **U1** | Schema & contextual features | New columns (hour_of_day, is_weekend, throughput_velocity, error_acceleration, is_surge, log_signature, log_payload); schema tests |
| **U2** | Feature store (materialized view) | `log_features_1m` table + `log_features_mv`; rolling baselines for adaptive inference |
| **U3** | Generator v2 & scenarios | Generator produces new fields; "Festival" and "Silent Failure" scenarios; tests |
| **U4** | Training pipeline v2 | FEATURE_COLUMNS v2, text_features, train.py and tests updated |
| **U5** | Adaptive inference view | View joins baselines, computes relative metrics, calls catboostEvaluate; latency test |
| **U6** | Docs & validation | README/runbook/troubleshooting updates; success metrics for v2 |

---

## 2. Phase Details

### Phase U1: Schema & Contextual Features

**Objective:** Introduce v2 schema as the primary schema; keep the existing v1 schema (e.g. `service_logs` or a copy) so we can revert if needed.

**Order of work (test-first):**

1. **Define schema contract v2**  
   Document exact new columns and types. **Keep** `user_agent`; **add**:
   - **Temporal:** `hour_of_day` (UInt8), `is_weekend` (UInt8).
   - **Velocity/surge:** `throughput_velocity` (Float64), `error_acceleration` (Float64), `is_surge` (UInt8).
   - **Log fingerprinting:** `log_signature` (String), `log_payload` (String).

2. **Implement DDL**  
   Create **new table** (e.g. `service_logs_v2`) with the full v2 schema as the primary table for v2. Keep the existing `service_logs` (v1) schema unchanged so it can be used for revert or comparison. Update `src/schema.py` and `src/config.py`: add `SERVICE_LOGS_V2_DDL`, `SERVICE_LOGS_V2_COLUMNS`, and table name constant for v2.

3. **Tests**  
   - Both tables exist; v2 has all new columns and types.  
   - Derivation rules documented (e.g. hour_of_day from timestamp at insert or in MV).

**Success:** Schema v2 table created; v1 retained; tests pass.

**Dependency:** None (can run on current codebase).

---

### Phase U2: Feature Store (Materialized View)

**Objective:** Maintain rolling 1-minute baselines (counts, error counts) per service and hour for use in adaptive inference.

**Order of work (test-first):**

1. **Define `log_features_1m` table**  
   AggregatingMergeTree with columns suitable for:
   - `service_id`, `window_start` (DateTime, minute), `hour_of_day` (UInt8).
   - Aggregate states: e.g. `total_reqs` (count), `error_reqs` (countIf status_code >= 500).  
   Use ClickHouse aggregate states (e.g. `countState`, `countIfState`) and merge functions (e.g. `countMerge`, `countIfMerge`) for correct semantics.  
   **TTL:** Set retention to **8–14 days** (recommended: 14 days) so the feature store does not grow indefinitely.

2. **Define `log_features_mv`**  
   Materialized view that reads from the v2 service logs table and writes to `log_features_1m`:  
   `GROUP BY service_id, toStartOfMinute(timestamp), toHour(timestamp)` with the chosen state columns.

3. **Tests**  
   - After insert into `service_logs`, MV has written into `log_features_1m`; query merged aggregates and assert consistency.  
   - Optional: test that MV only sees new data (no double-count from backfills) if that is a requirement.

**Success:** `log_features_1m` and `log_features_mv` created; integration test passes.

**Dependency:** U1 (schema must have `service_logs` with `timestamp`, `service_id`, `status_code` at minimum).

---

### Phase U3: Generator v2 & Scenarios

**Objective:** Synthetic data includes new fields. **Single flow with `--scenario` flag** (e.g. `--scenario festival | silent_failure | normal`) in the generator/ingest so all logic stays in `src/generator.py` and adheres to the shared schema; CI can run scenarios via CLI.

**Order of work (test-first):**

1. **Generator contract tests**  
   - Generator outputs new columns: `hour_of_day`, `is_weekend`, `throughput_velocity`, `error_acceleration`, `is_surge`, `log_signature`, `log_payload`; **keeps** `user_agent`.  
   - Ranges and types match schema (e.g. hour_of_day 0–23, is_surge 0/1).  
   - `log_signature` follows a standardized prefix pattern (e.g. `[AUTH]:[LOGIN]:[OK]`).

2. **Implement generator v2**  
   - Derive `hour_of_day`, `is_weekend` from timestamp.  
   - For velocity/surge: simulate or use placeholders (e.g. 1.0, 0.0, 0) in generator; real values come from the adaptive view at inference.

3. **Festival scenario** (elasticity / false positive suppression)  
   - **Definition:** Massive, planned traffic increase; system stays healthy.  
   - **Logic:** Over a 5-minute window, increase volume **10×**; keep `status_code` at 200 and `response_time_ms` in normal Gaussian range.  
   - **Features:** `throughput_velocity` will spike (e.g. > 5.0); `error_acceleration` remains ~1.0.  
   - **Expected:** Model learns that high throughput_velocity is not an anomaly when error ratio is stable; scores stay low.

4. **Silent Failure scenario** (semantic / out-of-distribution)  
   - **Definition:** Subtle failure: error codes unchanged, behavior changes (e.g. logic bug).  
   - **Logic:** Normal throughput; `status_code` remains 200; **log_signature** shifts to a new or rare value (e.g. `[ORDER]:[CHECKOUT]:[EMPTY_RESULT]`).  
   - **Features:** `error_acceleration` may stay flat; CatBoost flags via "new category" / out-of-distribution for that `service_id`.  
   - **Expected:** Model flags elevated anomaly score based on log_signature.

5. **Tests**  
   - Unit tests for generator columns and ranges.  
   - Integration test: run with `--scenario festival`, query view, assert scores below threshold during the burst window.

**Success:** Generator produces v2 schema; Festival and Silent Failure scenarios implemented and tested.

**Dependency:** U1 (schema). Velocity/surge can be stubbed in generator; real values come from U5 at inference. **Ingest:** Add `--scenario` (e.g. `festival | silent_failure | normal`) to ingest script and pass through to generator.

---

### Phase U4: Training Pipeline v2

**Objective:** Train CatBoost with new feature contract (numeric → categorical → text) and `text_features=['log_payload']`.

**Order of work (test-first):**

1. **Feature contract v2**  
   In `src/config.py`:
   - **Numeric first:** `[status_code, response_time_ms, throughput_velocity, error_acceleration, hour_of_day]` (order required for ClickHouse C library).
   - **Categorical:** `[service_id, endpoint, log_signature]`.  
   - **Text:** `[log_payload]`.  
   Add `TEXT_FEATURES`, `FEATURE_COLUMNS_V2` (or replace existing with v2); keep `CAT_FEATURES` aligned.

2. **Data loading**  
   Update `src/data.py`: load from v2 schema (all new columns). Handle missing columns gracefully if reading from mixed v1/v2 data.

3. **Train script**  
   Update `train.py`: use v2 feature list; call CatBoost with `cat_features=CAT_FEATURES`, `text_features=['log_payload']`. Export `catboost_model.bin` (v2).

4. **Tests**  
   - Feature contract test: expected columns and order.  
   - Model quality: F1 > 0.90 on v2 synthetic data (with Festival/Silent Failure in dataset or separate eval).  
   - Save/load with text_features.

**Success:** `train.py` produces v2 model; F1 target met; feature order documented.

**Dependency:** U1, U3 (schema and generator with new fields).  
**Note:** Assume `catboostEvaluate` supports text features; confirm during implementation. If not, inference view uses only numeric + categorical and document that `log_payload` is for Python training/batch scoring only.

---

### Phase U5: Adaptive Inference View

**Objective:** Replace or extend `anomalous_events` view: join with `log_features_1m` to compute `throughput_velocity` and `error_acceleration` (and optionally `is_surge`) per row, then call `catboostEvaluate` with v2 feature order.

**Order of work (test-first):**

1. **Define formulas (causal, no look-ahead)**  
   - **Throughput velocity (sliding window):**  
     - **Window:** Sliding 10 minutes; boundary = **current minute T** and the **9 preceding minutes** (T−9 to T−1), i.e. 10 discrete one-minute buckets.  
     - **Causality:** Window ends at current minute (real-time system cannot use future data).  
     - **Formula:** `throughput_velocity = current_minute_volume / avg(total_reqs over T−9..T)` (from `log_features_1m` merged aggregates).  
   - **Error acceleration (10-minute interval):**  
     - **Interval:** 10 minutes (aligned with throughput velocity for comparable evaluation).  
     - **Formula:** `error_acceleration = current_error_rate / error_rate_at_T_minus_10`.  
     - **Implementation:** In ClickHouse, use `lagInFrame` to get error rate from 10 rows back in a 1-minute bucketed view.  
     - **Interpretation:** 1.0 = flat; e.g. 3.0 = error density tripled → anomaly.  
   - **is_surge (per service_id, 60-minute trailing):**  
     - **Definition:** Boolean when **Z-Score of total request count per minute** > 3.0.  
     - **Scope:** Per **service_id** only (not per hour_of_day), to detect immediate bursts vs. immediate past.  
     - **Window:** **60-minute trailing:** `ROWS BETWEEN 60 PRECEDING AND CURRENT ROW` over 1-minute buckets.  
     - **Rationale:** Comparing to the last 60 minutes surfaces "unpredictable surge" rather than masking it with same-hour-of-day baseline.

2. **View DDL**  
   Update `src/inference.py`:  
   - Build SELECT that joins v2 service logs with `log_features_1m` (and/or a 1-minute bucketed view with window functions).  
   - Compute `throughput_velocity`, `error_acceleration`, `is_surge` using the formulas above.  
   - Call `catboostEvaluate(model_path, status_code, response_time_ms, throughput_velocity, error_acceleration, hour_of_day, service_id, endpoint, log_signature [, log_payload if supported])`.  
   - Output: timestamp, endpoint, anomaly_score, plus optional new fields.

3. **Tests**  
   - View exists and returns anomaly_score.  
   - Latency: batch scoring < 10 ms per batch (TRD).  
   - Festival scenario: scores low during high-volume phase.

**Success:** Adaptive view deployed; performance and Festival test pass.

**Dependency:** U2 (log_features_1m), U4 (v2 model).  
**Constraint:** Feature order in view must match training (numeric first, then categorical; text only if supported in ClickHouse).

---

### Phase U6: Docs & Validation

- Update README: v2 features, new schema, Festival/Silent Failure scenarios, optional text feature caveat.  
- Update runbook: ingest v2, train v2, create view v2.  
- Update or add troubleshooting for MV and adaptive view.  
- Success metrics: F1 > 90%, inference < 10 ms/batch, false positive suppression in Festival scenario.

---

## 3. Dependency Graph

```
U1 (Schema) ──┬──► U2 (MV) ──────────────────► U5 (Adaptive view)
              │
              ├──► U3 (Generator + scenarios)
              │           │
              └───────────┼──► U4 (Train v2) ──► U5
                          │
                          └──────────────────► U6 (Docs)
```

---

## 4. Design Decisions (Resolved)

The following decisions are fixed for v2 implementation; no further clarification needed.

| # | Topic | Decision |
|---|--------|----------|
| 1 | **user_agent** | **Keep** `user_agent`; **add** `log_signature` and `log_payload` (all three present in v2 schema). |
| 2 | **catboostEvaluate and text** | **Result:** ClickHouse `catboostEvaluate` **does not support text features**. The v2 model used in ClickHouse therefore uses **only numeric + categorical** features (8 features: status_code, response_time_ms, throughput_velocity, error_acceleration, hour_of_day, service_id, endpoint, log_signature). `log_payload` remains in the schema for analytics and potential **precomputed text embeddings**, but is **not passed** into `catboostEvaluate` in v2. |
| 3 | **Throughput velocity window** | **Sliding window.** Boundary: **current minute T** and **9 preceding minutes** (T−9 to T−1) — 10 discrete 1-minute points. **Causal:** window ends at current minute (no future data). |
| 4 | **Error acceleration** | Computed over a **10-minute interval.** Formula: **Current error rate / Error rate at T−10.** In ClickHouse: use `lagInFrame` to get error rate from 10 rows back in a 1-minute bucketed view. 1.0 = flat; 3.0 = tripling of error density = anomaly. Aligned with 10-minute throughput window. |
| 5 | **is_surge** | **Z-Score of total request count per minute** (total_reqs). **Scope:** per **service_id** only (not per hour_of_day). **Window:** **60-minute trailing:** `ROWS BETWEEN 60 PRECEDING AND CURRENT ROW`. Rationale: detect sudden bursts vs. immediate past; hour_of_day would compare to same hour and could mask rapid acceleration. |
| 6 | **Festival / Silent Failure** | **Single flow with `--scenario` flag** (e.g. `--scenario festival \| silent_failure \| normal`). Centralized in `src/generator.py`; ingest script passes `--scenario`; CI can run scenarios via CLI. Festival = 10× volume over 5 min, healthy metrics; Silent Failure = normal volume, new/rare log_signature. |
| 7 | **Backward compatibility** | **New schema (v2) is primary.** Introduce new table (e.g. `service_logs_v2`) for v2. **Keep old schema** (existing `service_logs`) unchanged so we can revert if needed. |
| 8 | **log_features_1m retention** | **TTL:** do **not** keep data indefinitely. Use a **retention of 8–14 days** (recommended: **14 days**). |

---

## 5. Test-First and Standards

- Same as v1: **Red–Green–Refactor**; unit tests for generator and feature logic; integration tests for schema, MV, ingest, train, view.  
- **CI:** All new tests must run in existing GitHub Actions workflow (ClickHouse service with auth).  
- **Ruff:** No new lint issues.  
- **Docs:** Any new config (e.g. FEATURE_COLUMNS_V2, TEXT_FEATURES) documented in README and config docstrings.

---

## 6. Success Criteria (v2)

| Metric | Target |
|--------|--------|
| Schema v2 | All new columns present and typed; tests pass |
| Feature store | log_features_1m populated by MV; merge semantics correct |
| Generator v2 | Festival (10× traffic, no anomaly) and Silent Failure (new signature) scenarios |
| Model v2 | F1 > 90% on v2 data; text_features used in training |
| Adaptive view | Joins baselines; computes velocity/acceleration; catboostEvaluate with v2 order; < 10 ms/batch |
| False positive suppression | Festival phase: anomaly scores below threshold |

Once the design decisions above are applied, implementation can proceed in the order U1 → U2 → U3 → U4 → U5 → U6.

**Step-by-step checklist:** [docs/STEP_BY_STEP_V2.md](./docs/STEP_BY_STEP_V2.md) — numbered actions per phase with file names and verification commands.
