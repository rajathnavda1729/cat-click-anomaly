# cat-click-anomaly

High-performance log anomaly detection pipeline using **ClickHouse** for OLAP storage and **CatBoost** for native categorical gradient boosting. Features in-database inference via `modelEvaluate`.

- **Requirements:** [Log Anomaly Detection System Requirements.md](./Log%20Anomaly%20Detection%20System%20Requirements.md)
- **Execution plan (test-first):** [EXECUTION_PLAN.md](./EXECUTION_PLAN.md)
- **Production vs POC (is_anomaly):** [EXECUTION_PLAN.md#6-production-vs-poc-how-is_anomaly-works](./EXECUTION_PLAN.md#6-production-vs-poc-how-is_anomaly-works)
- **ClickHouse + CatBoost fixes (for other projects):** [docs/CLICKHOUSE_CATBOOST_TROUBLESHOOTING.md](./docs/CLICKHOUSE_CATBOOST_TROUBLESHOOTING.md)
- **Consuming and validating anomaly output:** [docs/CONSUMING_ANOMALOUS_EVENTS.md](./docs/CONSUMING_ANOMALOUS_EVENTS.md)

---

## Production vs POC: the `is_anomaly` column

This repo is a **proof-of-concept** with **synthetic labeled data**. The `is_anomaly` column is set by the generator when we create each row (80% normal, 20% anomaly), so we have ground-truth labels for training and F1 evaluation.

**In production**, applications do not know if a request was anomalous; they only emit logs (timestamp, endpoint, status_code, etc.). So:

- **At ingest:** production logs would typically have **no** `is_anomaly` — only observability fields.
- **Labels** for training come from elsewhere: rules (e.g. status ≥ 500 → anomaly), human review, or unsupervised methods. Those labels live in a training dataset or view, not on the live stream.
- **At inference:** the model outputs an **anomaly score** for new logs; you treat high scores as "likely anomaly." There is no true label for incoming events.

See [EXECUTION_PLAN.md § 6](./EXECUTION_PLAN.md#6-production-vs-poc-how-is_anomaly-works) for the full explanation.

---

## Quick start (Phase 0)

**Prerequisites:** Python 3.10+, Docker and Docker Compose.

1. **Create virtualenv and install dependencies**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # or .venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

2. **Start ClickHouse**
   ```bash
   docker compose up -d
   ```
   Wait until the container is healthy (native port `9000`, HTTP `8123`).

3. **Run tests**
   - Unit only (no Docker required):
     ```bash
     pytest tests/ -m "not integration" -v
     ```
   - All tests (ClickHouse must be running):
     ```bash
     pytest tests/ -v
     ```

4. **Optional:** override connection via env
   ```bash
   export CLICKHOUSE_HOST=localhost CLICKHOUSE_PORT=9000
   ```

---

## Phase 1: Data ingestion

With ClickHouse running (`docker compose up -d`):

1. **Ingest 100k synthetic logs** (default)
   ```bash
   python ingest.py
   ```
   Options: `-n 100000` (rows), `--seed 42` (reproducibility).

2. **Run all tests** (includes schema, generator, ingest integration)
   ```bash
   pytest tests/ -v
   ```

---

## Phase 2: Training (CatBoost)

With ClickHouse running and data ingested (`python ingest.py`):

1. **Train the model** (reads from `service_logs`, writes `catboost_model.bin`)
   ```bash
   python train.py
   ```
   Options: `-o catboost_model.bin` (output path), `--iterations 500`, `--learning-rate 0.1`.

2. **Feature contract:** Column order is fixed in `src/config.py` (`FEATURE_COLUMNS`, `CAT_FEATURES`) so training and ClickHouse `modelEvaluate` stay in sync. Do not change order without updating both.

3. **Success:** F1 > 90% on synthetic data (enforced by `tests/test_train_model.py`).

---

## Phase 3: Inference in ClickHouse (real-time scoring)

To get the `anomalous_events` view and real-time scoring in ClickHouse:

1. **Download the CatBoost C evaluation library** (prebuilt for Linux; required for `catboostEvaluate` inside ClickHouse):
   ```bash
   bash scripts/download_libcatboostmodel.sh
   ```
   This fetches the library from [CatBoost releases](https://github.com/catboost/catboost/releases) and saves it as `libcatboostmodel.so` in the project root.
   - Default is Linux **x86_64**. Your Docker image is **arm64** (Apple Silicon), so use:
     ```bash
     rm -f libcatboostmodel.so
     bash scripts/download_libcatboostmodel.sh 1.2.10 aarch64
     ```
   - Optional: `bash scripts/download_libcatboostmodel.sh 1.2.5` for a specific version.

2. **Ensure you have a trained model** at project root:
   ```bash
   python train.py   # if you don't have catboost_model.bin yet
   ```

3. **Start ClickHouse with the CatBoost config** (this repo's `docker-compose.yml` already mounts `clickhouse/config.d` so `catboost_lib_path` is set):
   ```bash
   docker compose up -d --force-recreate
   ```
   Wait until the container is healthy.

4. **Create the scoring view:**
   ```bash
   python create_view.py
   ```

5. **Query anomalies** (e.g. via `clickhouse-client` or any SQL client on port 9000/8123):
   ```sql
   SELECT timestamp, service_id, endpoint, anomaly_score FROM anomalous_events WHERE anomaly_score > 0.5 LIMIT 10;
   ```

**Success:** View `anomalous_events` returns `anomaly_score`; inference tests run (`pytest tests/ -v` — no skips). TRD target is &lt; 10 ms per batch for scoring.

**If you skip the library:** Without `libcatboostmodel.so`, do not mount `clickhouse/config.d` (or remove that volume from `docker-compose.yml`) so ClickHouse starts; inference tests will be skipped.

---

## Phase 4: Validation & documentation

**Success metrics (TRD):**

| Metric | Target | How to verify |
|--------|--------|----------------|
| Preprocessing | Zero manual one-hot encoding | CatBoost `cat_features`; no one-hot in code |
| Inference latency | < 10 ms per batch in ClickHouse | `pytest tests/test_inference.py -v` (batch of 100 rows) |
| Detection quality | F1-score > 90% on synthetic labels | `pytest tests/test_train_model.py -v` |
| Data volume | 100k rows in `service_logs` | After `python ingest.py`: check row count or run `pytest tests/test_ingest.py` |
| Stack | Python 3.10+, ClickHouse v24.x+, CatBoost, Docker | See [EXECUTION_PLAN.md](./EXECUTION_PLAN.md) |

**Full pipeline validation (ingest → train → score via view):**

1. Start ClickHouse (with or without library bridge):
   ```bash
   docker compose up -d
   # Or with in-DB scoring: docker compose -f docker-compose.yml -f docker-compose.with-bridge.yml up -d
   ```
2. Ingest data, train, create view:
   ```bash
   python ingest.py
   python train.py
   python create_view.py   # requires lib + bridge if using catboostEvaluate
   ```
3. Run all tests to confirm metrics:
   ```bash
   pytest tests/ -v
   ```
4. Optional: one-page runbook for setup and re-training → [docs/RUNBOOK.md](./docs/RUNBOOK.md).

---

### Troubleshooting: "Connection reset by peer" when running create_view.py

1. **Check if the container is running:**  
   `docker ps --filter name=cat-click-anomaly-ch`  
   If it’s missing or restarting, ClickHouse is likely crashing on startup.

2. **Check logs:**  
   `docker logs cat-click-anomaly-ch --tail 80`  
   Look for errors about `libcatboostmodel.so` (wrong architecture, not found, or permission denied).

3. **Apple Silicon:** Use the **aarch64** library (see step 1 above). If you had `x86_64` before, remove it and download aarch64:
   ```bash
   rm -f libcatboostmodel.so
   bash scripts/download_libcatboostmodel.sh 1.2.10 aarch64
   docker compose up -d --force-recreate
   ```

4. **Start without CatBoost config:** If the server only starts when the CatBoost config is not loaded, run:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.no-catboost.yml up -d
   ```
   Then add `libcatboostmodel.so` (correct arch), switch back to normal `docker compose up -d --force-recreate`, and run `python create_view.py` again.

---

### In-DB CatBoost: "Child process was exited with return code 88"

The **official `clickhouse/clickhouse-server` Docker image does not include the `clickhouse-library-bridge` binary**. ClickHouse spawns that process to run `catboostEvaluate()`; if the binary is missing, the child exits with code 88 and you get **Code: 302**.

**Check:**  
`docker exec cat-click-anomaly-ch which clickhouse-library-bridge`  
If you see "not found", the image has no library bridge.

**Options:**

1. **Real-time scoring in Python (recommended workaround)**  
   Load the model and score in your app — no bridge needed:
   ```python
   from catboost import CatBoostClassifier
   import pandas as pd
   model = CatBoostClassifier()
   model.load_model("catboost_model.bin")
   # df has columns FEATURE_COLUMNS
   scores = model.predict_proba(df[FEATURE_COLUMNS])[:, 1]
   ```
   Use the same `FEATURE_COLUMNS` order as in `src/config.py`. This works with the standard Docker image.

2. **Custom image with the library bridge**  
   Build an image that adds the bridge from the ClickHouse APT repo (if available for your arch):
   ```bash
   docker build -f docker/Dockerfile.clickhouse-with-bridge -t clickhouse-with-catboost:24.8 .
   ```
   Then start ClickHouse using the custom image:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.with-bridge.yml up -d --force-recreate
   ```
   After that, run `python create_view.py` as usual. If the package `clickhouse-library-bridge` is not in the repo for your platform, the build will fail; in that case use option 1 (Python scoring).

---

## Project layout

```
├── docs/
│   ├── CLICKHOUSE_CATBOOST_TROUBLESHOOTING.md   # Step-by-step fixes for in-DB CatBoost (reusable)
│   ├── CONSUMING_ANOMALOUS_EVENTS.md            # How to consume and validate view output
│   └── RUNBOOK.md                               # First-time setup + re-train model
├── docker/                # Dockerfile.clickhouse-with-bridge (optional custom image)
├── docker-compose.yml     # ClickHouse 24.x; /workspace + config.d mounted
├── docker-compose.with-bridge.yml   # Override to use custom image with library bridge
├── clickhouse/config.d/  # catboost.xml (catboost_lib_path) for in-DB inference
├── scripts/
│   ├── download_libcatboostmodel.sh   # Download prebuilt CatBoost C library
│   └── validate_anomaly_output.py    # Validate anomaly_score vs is_anomaly, threshold, precision/recall
├── ingest.py             # Create service_logs + insert synthetic data
├── train.py              # Train CatBoost from ClickHouse, save catboost_model.bin
├── create_view.py        # Create anomalous_events view (catboostEvaluate)
├── requirements.txt
├── pyproject.toml        # pytest config
├── src/
│   ├── config.py         # ClickHouse connection, schema, FEATURE_COLUMNS, MODEL_PATH_IN_CONTAINER
│   ├── schema.py         # ensure_service_logs_table, schema validation
│   ├── data.py           # load_training_data() from ClickHouse
│   ├── inference.py      # anomalous_events view DDL, ensure_anomalous_events_view()
│   └── generator.py      # Synthetic log generator (80% normal, 20% anomaly)
├── tests/
│   ├── conftest.py       # pytest fixtures (ClickHouse client)
│   ├── test_clickhouse_connectivity.py  # Phase 0 smoke tests
│   ├── test_schema.py    # Schema contract tests
│   ├── test_generator.py # Generator unit tests
│   ├── test_ingest.py    # Ingest integration tests
│   ├── test_train_data.py   # Data loading & feature contract
│   ├── test_train_model.py  # F1 > 90%, model save/load
│   └── test_inference.py    # View + anomaly_score; skipped if CatBoost lib not available
└── .cursor/rules/        # Project standards (TDD, Python, Docker)
```

**Phase 4** — Success metrics and full-pipeline validation are in the section above; runbook: [docs/RUNBOOK.md](./docs/RUNBOOK.md).
