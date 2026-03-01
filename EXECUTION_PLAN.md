# Log Anomaly Detection System — Execution Plan

This document defines the **execution plan**, **test-first development strategy**, and **success criteria** for the project. It aligns with [Log Anomaly Detection System Requirements.md](./Log%20Anomaly%20Detection%20System%20Requirements.md).

---

## 1. Execution Plan Overview

| Phase | Goal | Deliverables |
|-------|------|--------------|
| **0** | Environment & standards | Docker Compose, Python env, Cursor rules, test harness |
| **1** | Schema & ingestion | `service_logs` table, `ingest.py`, synthetic data (100k rows) |
| **2** | Training pipeline | `train.py`, CatBoost model export, feature alignment |
| **3** | Inference in ClickHouse | XML config, `anomalous_events` view, `modelEvaluate` usage |
| **4** | Validation & docs | Success metrics, README, runbook |

---

## 2. Phase Details

### Phase 0: Environment & Standards (Test-First Setup)

- **Docker Compose**: Single-node ClickHouse (v24.x+), optional Jupyter/app container.
- **Python**: 3.10+; use `requirements.txt` or `pyproject.toml`; virtualenv in `.venv`.
- **Tests**: pytest; structure `tests/` with unit and integration tests; run via `pytest` (and in CI).
- **Cursor rules**: `.cursor/rules/` — project standards, Python conventions, Docker/ClickHouse, test-first reminders.

**Test-first checkpoint**: `pytest tests/` runs (even if only smoke tests); ClickHouse reachable via Docker.

---

### Phase 1: Data Ingestion & Schema

**Order of work (test-first):**

1. **Define schema contract**  
   Document exact column names, types, and table engine. Write a test that validates the table exists and matches schema (e.g., via ClickHouse client or small script).

2. **Implement table creation**  
   DDL for `service_logs`: `timestamp` (DateTime64), `service_id`, `endpoint`, `status_code`, `response_time_ms`, `user_agent`; MergeTree ordered by `(timestamp, service_id)`.

3. **Synthetic log generator (test-first)**  
   - Tests for distribution: ~80% normal, ~20% anomaly (by label).  
   - Tests for required fields and value ranges (e.g., status_code, response_time_ms).  
   - Tests for categorical coverage (service_id, endpoint, user_agent).  
   Then implement generator to satisfy these tests.

4. **Ingest script `ingest.py`**  
   - Creates table if not exists; inserts 100k rows from generator.  
   - Integration test: run ingest, then assert row count and basic stats (e.g., anomaly ratio).

**Success**: Table exists, 100k rows ingested; pytest for schema, generator, and ingest passes.

---

### Phase 2: Training Pipeline (CatBoost)

**Order of work (test-first):**

1. **Data loading tests**  
   Test that we can query ClickHouse and get a DataFrame with columns: `service_id`, `endpoint`, `status_code`, `response_time_ms`, `user_agent`, `is_anomaly`.  
   Optional: test that feature engineering (hour-of-day, day-of-week, rolling avg latency) is computed in SQL or in Python and matches expected form.

2. **Feature contract tests**  
   Assert exact feature list and dtypes; assert categorical list `['service_id', 'endpoint', 'user_agent']` and that column order is stable (critical for CatBoost/ClickHouse alignment).

3. **Train script `train.py`**  
   - Pull data from ClickHouse.  
   - Binary target `is_anomaly`.  
   - CatBoost: `iterations=500`, `learning_rate=0.1`, `cat_features=['service_id', 'endpoint', 'user_agent']`.  
   - Export `catboost_model.bin` (or `model.bin` as per TRD).

4. **Model quality test**  
   Assert F1-score on synthetic test set > 0.90 (success metric from TRD).

**Success**: `train.py` runs; model file produced; F1 > 90%; column order documented and tested.

---

### Phase 3: Inference in ClickHouse

**Order of work (test-first):**

1. **Config tests**  
   Document expected XML config (user_defined_models or modelEvaluate); add a test or script that verifies ClickHouse loads the model (e.g., no config error on startup or on first use).

2. **View + modelEvaluate**  
   Create view `anomalous_events` that scores incoming log rows using `modelEvaluate`.  
   Test: insert a few rows, query view, assert scores present and in expected range.

3. **Performance test**  
   Batch scoring: target < 10 ms per batch (TRD); measure with a small benchmark and document batch size.

**Success**: View returns anomaly scores; performance check passes; no manual one-hot encoding (CatBoost handles categories).

---

### Phase 4: Validation & Documentation

- Run full pipeline (ingest → train → load model → score via view).  
- Record success metrics: F1 > 90%, inference < 10 ms per batch, zero manual one-hot encoding.  
- Update README with: how to run Docker, ingest, train, and run inference; pro-tip on categorical column order.  
- Optional: one-page runbook for “first-time setup” and “re-train model”.

---

## 3. Test-First Development Strategy

- **Red–Green–Refactor**: Write a failing test first, then implement the minimum code to pass, then refactor.  
- **Layers**:
  - **Unit**: Pure Python (generator, feature builders, small helpers) — no ClickHouse.
  - **Integration**: ClickHouse running (Docker); table creation, ingest, query, view, modelEvaluate.
- **Naming**: `test_<module>_<behavior>.py` or `tests/test_ingest.py`, `tests/test_train.py`, `tests/test_inference.py`.  
- **CI**: Run `pytest tests/` (and optionally lint/type-check) on every push/PR.  
- **Data**: Prefer deterministic seeds in synthetic generator so tests are reproducible.  
- **Order of implementation**: Schema/contract → tests that validate contract → implementation → integration test for the component.

---

## 4. Success Metrics (from TRD)

| Metric | Target |
|--------|--------|
| Preprocessing | Zero manual one-hot encoding; CatBoost handles categoricals |
| Inference latency | < 10 ms per batch in ClickHouse |
| Detection quality | F1-score > 90% on synthetic anomaly labels |
| Data volume | 100k rows in `service_logs` |
| Stack | Python 3.10+, ClickHouse v24.x+, CatBoost, Docker Compose |

---

## 5. Repository Standards (Summary)

- **Code style**: PEP 8; use Ruff (or Black + isort) for formatting/lint.  
- **Types**: Use type hints for public functions and APIs.  
- **Secrets**: No credentials in repo; use env vars or `.env` (and keep `.env` in `.gitignore`).  
- **Documentation**: Docstrings for public modules and functions; README for run instructions.  
- **Cursor rules**: Follow `.cursor/rules/` for project-wide and file-specific conventions.

Detailed standards are in `.cursor/rules/` and apply automatically when working in this repo.

---

## 6. Production vs POC: How `is_anomaly` Works

### In this POC

- **How it's marked:** The synthetic log generator (`src/generator.py`) decides up front that a fixed fraction of rows (default 20%) are "anomaly" and the rest "normal." It sets `is_anomaly` to **0** or **1** and then generates the other fields to match (e.g. normal → status 200, Gaussian latency; anomaly → 5xx, high latency, unusual user_agent).
- **Why:** We need **ground-truth labels** to train a supervised model and to measure F1. Synthetic data gives us that for the demo.

### In a traditional production setup

When logs are **pushed from the application**, there is no built-in "anomaly" flag. The app only records what it observed (status, latency, endpoint, user_agent, etc.). So:

| Stage | What you have | Role of "anomaly" |
|-------|----------------|--------------------|
| **Ingest (live)** | Raw logs only | None — you store features, no label. |
| **Training (offline)** | Historical data + labels | Labels come from rules, human review, or unsupervised methods (see below). |
| **Inference (live or batch)** | New logs | Model outputs an **anomaly score**; you treat high score as "likely anomaly." No true label for new events. |

**Ways production systems get labels for training:**

1. **Rule-based (offline)** — Run batch jobs over history: e.g. "status ≥ 500 → anomaly," "response_time_ms > P99 → anomaly," "user_agent in blocklist → anomaly." Write results to a **training table** or view that includes `is_anomaly` (or equivalent).
2. **Human labeling** — Incidents or alerts are reviewed; analysts tag "this was an anomaly." Those tags are joined back to log rows (e.g. by time range, service, trace_id) to build a labeled dataset.
3. **Unsupervised / semi-supervised** — Train without labels (e.g. one-class or clustering), then use model scores or cluster membership as a pseudo-label for further training or alerting. No explicit `is_anomaly` at ingest; the **model output** is the anomaly signal.
4. **Synthetic (this repo)** — Generate both normal and anomalous traffic and tag it. Useful for POC and benchmarking, not as a substitute for real production labels.

### Summary

- **POC:** One table stores synthetic logs **with** `is_anomaly` so we can train and evaluate.
- **Production-style:** Live logs table has **no** `is_anomaly`; labels exist only in a training dataset/view (from rules, humans, or unsupervised). At serve time, only the **model score** indicates anomaly likelihood.
