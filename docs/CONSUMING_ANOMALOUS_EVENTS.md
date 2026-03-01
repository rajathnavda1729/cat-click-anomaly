# Consuming and validating `anomalous_events` output

How to **consume** the anomaly scores from the `anomalous_events` view and how to **validate** that the output is meaningful.

---

## What the view returns

| Column          | Type     | Description |
|-----------------|----------|-------------|
| `timestamp`     | DateTime | Log event time |
| `service_id`    | String   | Service identifier |
| `endpoint`      | String   | Request path |
| `status_code`   | UInt16   | HTTP status |
| `response_time_ms` | UInt32 | Latency in ms |
| `user_agent`    | String   | Client user agent |
| `is_anomaly`    | UInt8    | Ground-truth label (0/1); only in POC/synthetic data |
| `anomaly_score` | Float64  | Model score (higher = more likely anomaly) |

`anomaly_score` is the **raw CatBoost output** (not necessarily 0–1). Use it for **ranking** (e.g. top-N highest scores) or apply a threshold after inspecting the distribution.

---

## How to consume the output

### 1. SQL (any ClickHouse client)

```sql
-- Top 20 highest-scoring events (most likely anomalies)
SELECT timestamp, service_id, endpoint, status_code, response_time_ms, anomaly_score
FROM anomalous_events
ORDER BY anomaly_score DESC
LIMIT 20;

-- Events in the last hour above a score threshold (tune threshold from data)
SELECT timestamp, endpoint, status_code, anomaly_score
FROM anomalous_events
WHERE timestamp >= now() - INTERVAL 1 HOUR
  AND anomaly_score > 5
ORDER BY timestamp DESC;

-- Count by endpoint for high-scoring events
SELECT endpoint, count() AS cnt
FROM anomalous_events
WHERE anomaly_score > 5
GROUP BY endpoint
ORDER BY cnt DESC;
```

### 2. Python (clickhouse-driver)

```python
from clickhouse_driver import Client
from src.config import get_clickhouse_connection_params, ANOMALOUS_EVENTS_VIEW

client = Client(**get_clickhouse_connection_params())

# Top anomalies
rows = client.execute(f"""
    SELECT timestamp, endpoint, status_code, response_time_ms, anomaly_score
    FROM {ANOMALOUS_EVENTS_VIEW}
    ORDER BY anomaly_score DESC
    LIMIT 100
""")
for row in rows:
    print(row)

# Or as pandas DataFrame (optional: pip install pandas)
# import pandas as pd
# df = pd.DataFrame(rows, columns=["timestamp", "endpoint", "status_code", "response_time_ms", "anomaly_score"])
```

### 3. HTTP API (curl / any HTTP client)

```bash
curl -s "http://localhost:8123/?query=SELECT%20timestamp%2C%20endpoint%2C%20anomaly_score%20FROM%20anomalous_events%20ORDER%20BY%20anomaly_score%20DESC%20LIMIT%2010"
```

### 4. Downstream use cases

- **Alerts:** Run a scheduled query; if `count() WHERE anomaly_score > threshold` exceeds a limit, send an alert.
- **Dashboards:** Point Grafana (or similar) at ClickHouse and build panels from `anomalous_events` (e.g. time series of high-score count, top endpoints by score).
- **Export:** Stream or batch-export high-scoring rows to a data lake or incident tool.

---

## How to validate the output

### 1. Sanity checks (no labels needed)

- **Row count:** `SELECT count() FROM anomalous_events` should equal `SELECT count() FROM service_logs`.
- **Scores present:** All rows should have a non-NULL `anomaly_score`; check with `SELECT count() FROM anomalous_events WHERE anomaly_score IS NULL` (should be 0).
- **Score distribution:** Run the validation script below to see min/max/percentiles and confirm scores are spread (not all the same).

### 2. Validation against ground truth (POC only)

In this repo we have synthetic data with `is_anomaly` (0/1). You can check that **high scores tend to align with `is_anomaly = 1`**:

- Compare mean/median `anomaly_score` for `is_anomaly = 0` vs `is_anomaly = 1` (anomalies should have higher scores).
- Pick a threshold and compute precision/recall vs `is_anomaly` (see script below).

**Run the validation script:**

```bash
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
python scripts/validate_anomaly_output.py
```

This prints score stats by `is_anomaly`, a suggested threshold, and optional precision/recall. Use it to confirm the model is ranking anomalies higher before you rely on scores in production.

### 3. Threshold choice

- **POC:** Use the script output and/or SQL to inspect score percentiles; choose a threshold (e.g. 90th or 95th percentile) and compare predicted positives vs `is_anomaly`.
- **Production:** You typically have no labels; use domain rules (e.g. “alert if score > X” or “top N per hour”) and tune X/N from feedback and false-positive rate.

---

## Quick validation commands

```bash
# Count and basic stats (from project root)
python -c "
from clickhouse_driver import Client
from src.config import get_clickhouse_connection_params, ANOMALOUS_EVENTS_VIEW
c = Client(**get_clickhouse_connection_params())
n = c.execute(f'SELECT count() FROM {ANOMALOUS_EVENTS_VIEW}')[0][0]
stats = c.execute(f'SELECT min(anomaly_score), max(anomaly_score), avg(anomaly_score) FROM {ANOMALOUS_EVENTS_VIEW}')[0]
print(f'Rows: {n}, score min/max/avg: {stats[0]:.4f} / {stats[1]:.4f} / {stats[2]:.4f}')
"

# Full validation (scores vs is_anomaly, threshold, precision/recall)
source .venv/bin/activate
python scripts/validate_anomaly_output.py
```
