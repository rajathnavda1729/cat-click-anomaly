# v2.0 Implementation — Step-by-Step Checklist

Follow these steps **in order**. Each step is a single, verifiable action. Run tests after the steps marked with ✓.

Reference: [EXECUTION_PLAN_V2.md](./EXECUTION_PLAN_V2.md) and [Log Anomaly Detection Upgrade Plan.md](./Log%20Anomaly%20Detection%20Upgrade%20Plan.md).

---

## Phase U1: Schema & Contextual Features

| Step | Action | File(s) | Verify |
|------|--------|---------|--------|
| **U1.1** | Add constants for v2 table name and columns. Define full v2 column list: timestamp, service_id, endpoint, status_code, response_time_ms, user_agent, **hour_of_day**, **is_weekend**, **throughput_velocity**, **error_acceleration**, **is_surge**, **log_signature**, **log_payload**, is_anomaly. Types: hour_of_day UInt8, is_weekend UInt8, throughput_velocity Float64, error_acceleration Float64, is_surge UInt8, log_signature String, log_payload String. | `src/config.py` | — |
| **U1.2** | Add `SERVICE_LOGS_V2_TABLE = "service_logs_v2"` and `SERVICE_LOGS_V2_DDL` (CREATE TABLE with all v2 columns). Engine: MergeTree(), ORDER BY (timestamp, service_id). | `src/config.py` | — |
| **U1.3** | Add `SERVICE_LOGS_V2_COLUMNS` list of (name, type) for tests. | `src/config.py` | — |
| **U1.4** | In `src/schema.py`, add `ensure_service_logs_v2_table(client)` that runs `SERVICE_LOGS_V2_DDL`, and `get_table_columns(..., table=SERVICE_LOGS_V2_TABLE)` support (reuse or overload). | `src/schema.py` | — |
| **U1.5** | Add integration test: both `service_logs` and `service_logs_v2` exist; `get_table_columns` for v2 returns `SERVICE_LOGS_V2_COLUMNS`. | `tests/test_schema.py` (or new `tests/test_schema_v2.py`) | `pytest tests/test_schema*.py -v` ✓ |

---

## Phase U2: Feature Store (Materialized View)

| Step | Action | File(s) | Verify |
|------|--------|---------|--------|
| **U2.1** | Define DDL for `log_features_1m`: AggregatingMergeTree, columns: service_id String, window_start DateTime, hour_of_day UInt8, total_reqs AggregateFunction(count), error_reqs AggregateFunction(countIf, UInt8). ORDER BY (service_id, window_start). Add TTL: `window_start + INTERVAL 14 DAY` (or 8–14 days as chosen). | `src/config.py` or `src/schema.py` | — |
| **U2.2** | Define DDL for `log_features_mv`: MATERIALIZED VIEW reading from `service_logs_v2`, writing TO `log_features_1m`. SELECT service_id, toStartOfMinute(timestamp) AS window_start, toHour(timestamp) AS hour_of_day, countState() AS total_reqs, countIfState(status_code >= 500) AS error_reqs. GROUP BY service_id, window_start, hour_of_day. | `src/schema.py` or new `src/feature_store.py` | — |
| **U2.3** | Add function `ensure_log_features_1m(client)` (and ensure_log_features_mv) that creates table and MV if not exist. | `src/schema.py` or `src/feature_store.py` | — |
| **U2.4** | Add integration test: insert rows into service_logs_v2, then query log_features_1m with countMerge(total_reqs), countIfMerge(error_reqs); assert counts consistent. | `tests/test_feature_store.py` (new) | `pytest tests/test_feature_store.py -v` ✓ |

---

## Phase U3: Generator v2 & Scenarios

| Step | Action | File(s) | Verify |
|------|--------|---------|--------|
| **U3.1** | Extend `generate_logs()` to accept optional `scenario: str = "normal"` and return DataFrame with v2 columns. Add columns: hour_of_day (from timestamp), is_weekend (from timestamp), throughput_velocity, error_acceleration, is_surge (placeholders: e.g. 1.0, 0.0, 0), log_signature (e.g. [SVC]:[ACTION]:[RESULT] from small grammar), log_payload (short unstructured string). Keep user_agent. | `src/generator.py` | — |
| **U3.2** | Implement scenario **"festival"**: for a 5-minute window, emit 10× rows (same time bucket), all is_anomaly=0, status_code=200, response_time_ms normal. Other minutes normal volume. | `src/generator.py` | — |
| **U3.3** | Implement scenario **"silent_failure"**: normal volume; for a defined window, set log_signature to a new/rare value (e.g. [ORDER]:[CHECKOUT]:[EMPTY_RESULT]); status_code=200. | `src/generator.py` | — |
| **U3.4** | Add unit tests: generator output has all v2 columns; hour_of_day in 0–23, is_surge in {0,1}; log_signature matches pattern; scenario festival produces 10× count in burst window; scenario silent_failure produces rare log_signature in target window. | `tests/test_generator.py` | `pytest tests/test_generator.py -v` ✓ |
| **U3.5** | Update `ingest.py`: add `--scenario` (choices: normal, festival, silent_failure). Default normal. Insert into **service_logs_v2** (not service_logs). Use column list that matches v2 table. | `ingest.py` | `python ingest.py -n 1000 --scenario normal` ✓ |
| **U3.6** | Add integration test: run ingest with `--scenario festival`, then (after U5) query anomalous_events for burst window and assert anomaly_score below threshold. | `tests/test_ingest.py` or new test | Optional after U5 ✓ |

---

## Phase U4: Training Pipeline v2

| Step | Action | File(s) | Verify |
|------|--------|---------|--------|
| **U4.1** | In config, add FEATURE_COLUMNS_V2: numeric first [status_code, response_time_ms, throughput_velocity, error_acceleration, hour_of_day], then categorical [service_id, endpoint, log_signature], then text [log_payload]. Add CAT_FEATURES_V2 = [service_id, endpoint, log_signature], TEXT_FEATURES_V2 = [log_payload]. | `src/config.py` | — |
| **U4.2** | Update `load_training_data()` to read from **service_logs_v2**, select FEATURE_COLUMNS_V2 + TARGET, handle all new columns. | `src/data.py` | — |
| **U4.3** | Update `train.py`: use FEATURE_COLUMNS_V2, CAT_FEATURES_V2, TEXT_FEATURES_V2; call CatBoostClassifier(..., cat_features=CAT_FEATURES_V2, text_features=TEXT_FEATURES_V2). Save to catboost_model_v2.bin or overwrite; document in config. | `train.py`, `src/config.py` | — |
| **U4.4** | Add/update feature contract test: loaded columns match FEATURE_COLUMNS_V2 order and dtypes. | `tests/test_train_data.py` | `pytest tests/test_train_data.py -v` ✓ |
| **U4.5** | Update model quality test: train on v2 data, assert F1 > 0.90. Save/load with text_features. | `tests/test_train_model.py` | `pytest tests/test_train_model.py -v` ✓ |
| **U4.6** | Run full ingest (v2) + train; confirm catboost_model_v2.bin (or chosen path) is produced. | — | `python ingest.py -n 50000` then `python train.py` ✓ |

---

## Phase U5: Adaptive Inference View

| Step | Action | File(s) | Verify |
|------|--------|---------|--------|
| **U5.1** | Create a 1-minute bucketed view or CTE from log_features_1m with merged aggregates: total_reqs = countMerge(total_reqs), error_reqs = countIfMerge(error_reqs), error_rate = error_reqs / total_reqs. | `src/inference.py` or SQL in doc | — |
| **U5.2** | Implement throughput_velocity in SQL: for each row (service_id, window_start), get current minute volume and avg(total_reqs) over ROWS BETWEEN 9 PRECEDING AND CURRENT ROW (10 buckets T−9..T). velocity = current_volume / nullIf(avg, 0). | `src/inference.py` | — |
| **U5.3** | Implement error_acceleration: error_rate_current / lagInFrame(error_rate, 10). Use 1-minute bucketed data; lagInFrame(..., 10) = value 10 rows back. | `src/inference.py` | — |
| **U5.4** | Implement is_surge: Z-Score of total_reqs per service_id over ROWS BETWEEN 60 PRECEDING AND CURRENT ROW; is_surge = (z_score > 3.0) ? 1 : 0. | `src/inference.py` | — |
| **U5.5** | Build adaptive view DDL: SELECT from service_logs_v2 joined to (bucketed log_features_1m with velocity, acceleration, is_surge), then catboostEvaluate(model_path, status_code, response_time_ms, throughput_velocity, error_acceleration, hour_of_day, service_id, endpoint, log_signature [, log_payload if supported]). Output timestamp, endpoint, anomaly_score, etc. Feature order must match training (numeric first, then categorical, then text if supported). | `src/inference.py` | — |
| **U5.6** | Add ensure_anomalous_events_view_v2(client, model_path) or update existing to use v2 table and v2 feature list. Update create_view.py to use v2 model path and v2 view. | `src/inference.py`, `create_view.py` | — |
| **U5.7** | Add integration test: view returns anomaly_score; latency < 10 ms per batch. Add Festival test: after ingest --scenario festival, query view for burst window, assert scores below threshold. | `tests/test_inference.py` | `pytest tests/test_inference.py -v` ✓ |

---

## Phase U6: Docs & Validation

| Step | Action | File(s) | Verify |
|------|--------|---------|--------|
| **U6.1** | Update README: add "v2.0" section describing new schema (service_logs_v2), contextual features, Festival/Silent Failure scenarios, `--scenario` flag, and that in-DB view uses log_features_1m for velocity/acceleration. Note text feature support in catboostEvaluate (or Python-only if not supported). | `README.md` | — |
| **U6.2** | Update runbook: first-time setup and re-train for v2 (ingest to service_logs_v2, train v2, create view v2). Add `--scenario` examples. | `docs/RUNBOOK.md` | — |
| **U6.3** | Add troubleshooting note for MV/adaptive view (e.g. log_features_1m empty, TTL, lagInFrame behavior). | `docs/CLICKHOUSE_CATBOOST_TROUBLESHOOTING.md` or new doc | — |
| **U6.4** | Run full pipeline: ingest (v2) → train (v2) → create view (v2) → validate_anomaly_output (on v2 view). Record success metrics (F1, latency, Festival false positive suppression). | — | Manual ✓ |

---

## Quick Reference: Execution Order

```
U1.1 → U1.2 → U1.3 → U1.4 → U1.5   (schema)
  ↓
U2.1 → U2.2 → U2.3 → U2.4          (feature store)
  ↓
U3.1 → U3.2 → U3.3 → U3.4 → U3.5 → U3.6   (generator + ingest)
  ↓
U4.1 → U4.2 → U4.3 → U4.4 → U4.5 → U4.6   (training)
  ↓
U5.1 → U5.2 → U5.3 → U5.4 → U5.5 → U5.6 → U5.7   (adaptive view)
  ↓
U6.1 → U6.2 → U6.3 → U6.4   (docs & validation)
```

---

## Checklist (copy and tick off)

- [ ] U1.1 – U1.5  Schema v2
- [ ] U2.1 – U2.4  Feature store
- [ ] U3.1 – U3.6  Generator + scenarios + ingest
- [ ] U4.1 – U4.6  Training v2
- [ ] U5.1 – U5.7  Adaptive view
- [ ] U6.1 – U6.4  Docs & validation
