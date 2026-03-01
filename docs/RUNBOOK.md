# Runbook: Log Anomaly Detection (ClickHouse + CatBoost)

One-page reference for **first-time setup** and **re-training the model**.

---

## First-time setup

**Prerequisites:** Python 3.10+, Docker and Docker Compose.

| Step | Command / action |
|------|-------------------|
| 1 | `python3 -m venv .venv` then `source .venv/bin/activate` (or `.venv\Scripts\activate` on Windows) |
| 2 | `pip install -r requirements.txt` |
| 3 | `docker compose up -d` — wait until ClickHouse is healthy (e.g. `curl -s http://localhost:8123/ping` → `Ok.`) |
| 4 | `python ingest.py` — creates `service_logs` and inserts 100k synthetic rows |
| 5 | `python train.py` — trains CatBoost, writes `catboost_model.bin` |
| 6 | **(In-DB scoring only)** Download CatBoost C library: `bash scripts/download_libcatboostmodel.sh` (use `aarch64` on Apple Silicon). Then use custom image: `docker build -f docker/Dockerfile.clickhouse-with-bridge -t clickhouse-with-catboost:24.8 .` and `docker compose -f docker-compose.yml -f docker-compose.with-bridge.yml up -d --force-recreate` |
| 7 | **(In-DB scoring only)** `python create_view.py` — creates `anomalous_events` view |
| 8 | Validate: `pytest tests/ -v` |

**If you hit issues:** See [CLICKHOUSE_CATBOOST_TROUBLESHOOTING.md](./CLICKHOUSE_CATBOOST_TROUBLESHOOTING.md) (connection reset, exit code 88, “Column 0 should be numeric”).

---

## Re-train the model

Use when you have **new or updated data** in `service_logs` or changed features/hyperparameters.

| Step | Command / action |
|------|-------------------|
| 1 | Ensure ClickHouse is running: `docker compose up -d` (or with-bridge override if using in-DB scoring). |
| 2 | **(Optional)** Ingest fresh data: `python ingest.py -n 100000 --seed <new_seed>` or truncate and re-ingest as needed. |
| 3 | Train: `python train.py` (optionally `-o catboost_model.bin --iterations 500 --learning-rate 0.1`). |
| 4 | **(In-DB scoring only)** Recreate the view so ClickHouse uses the new model: `python create_view.py`. |
| 5 | Validate: `pytest tests/ -v` (especially `test_train_model.py` for F1, `test_inference.py` for view/latency). |

**Important:** Feature order is fixed in `src/config.py` (`FEATURE_COLUMNS`: numeric first, then categorical). Do not change it without updating training and the view together; then retrain and run `create_view.py` again.

---

## Quick reference

- **Ingest:** `python ingest.py` (-n, --seed)
- **Train:** `python train.py` (-o, --iterations, --learning-rate)
- **Create view (in-DB scoring):** `python create_view.py`
- **Tests:** `pytest tests/ -v` (all); `pytest tests/ -m "not integration" -v` (unit only)
- **Query anomalies:** `SELECT timestamp, endpoint, anomaly_score FROM anomalous_events ORDER BY anomaly_score DESC LIMIT 10;`
- **Validate scores (POC):** `python scripts/validate_anomaly_output.py` — see [CONSUMING_ANOMALOUS_EVENTS.md](./CONSUMING_ANOMALOUS_EVENTS.md).

---

## Does the view include newly ingested logs?

**Yes.** The `anomalous_events` view is a **live view**: it runs `SELECT ... FROM service_logs` (with `catboostEvaluate(...)`) every time you query it. Any new rows inserted into `service_logs` are included automatically—no need to recreate the view or refresh anything.

**How to validate:**

1. **Record current row count** (table and view should match):
   ```bash
   # From host (replace with clickhouse-client if you prefer)
   python -c "
   from clickhouse_driver import Client
   from src.config import get_clickhouse_connection_params, SERVICE_LOGS_TABLE, ANOMALOUS_EVENTS_VIEW
   c = Client(**get_clickhouse_connection_params())
   n_table = c.execute(f'SELECT count() FROM {SERVICE_LOGS_TABLE}')[0][0]
   n_view  = c.execute(f'SELECT count() FROM {ANOMALOUS_EVENTS_VIEW}')[0][0]
   print(f'service_logs: {n_table}, anomalous_events: {n_view}')
   "
   ```
2. **Ingest more rows** (e.g. 10k extra):
   ```bash
   python ingest.py -n 10000 --seed 123
   ```
3. **Check counts again** — both should increase by 10,000; table and view counts should still match.
4. **Check recent data** — new rows should have recent timestamps and scores:
   ```bash
   python -c "
   from clickhouse_driver import Client
   from src.config import get_clickhouse_connection_params, ANOMALOUS_EVENTS_VIEW
   c = Client(**get_clickhouse_connection_params())
   rows = c.execute(f'SELECT timestamp, endpoint, anomaly_score FROM {ANOMALOUS_EVENTS_VIEW} ORDER BY timestamp DESC LIMIT 5')
   for r in rows:
       print(r)
   "
   ```

If the view is missing or CatBoost isn’t configured, the view query will fail; see [CLICKHOUSE_CATBOOST_TROUBLESHOOTING.md](./CLICKHOUSE_CATBOOST_TROUBLESHOOTING.md).
