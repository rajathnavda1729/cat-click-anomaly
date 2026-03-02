# ClickHouse + CatBoost inference: troubleshooting and fixes

This document records the issues we hit when enabling **in-database CatBoost inference** in ClickHouse (`catboostEvaluate`) and the step-by-step fixes. Use it as a reference for other projects using ClickHouse with CatBoost.

---

## Goal

- Store logs in ClickHouse, train a CatBoost model in Python, save `catboost_model.bin`.
- Run **real-time scoring inside ClickHouse** via a view that calls `catboostEvaluate(model_path, feature1, feature2, ...)`.
- Query a view like `anomalous_events` that returns `anomaly_score` per row.

---

## Issue 1: Connection reset by peer (cannot reach ClickHouse from host)

**Symptom:**  
Connecting from the host (e.g. `python create_view.py` or `clickhouse-client` on `localhost:9000` / `localhost:8123`) fails with “Connection reset by peer” or similar. The container is running but not accepting connections from outside.

**Cause:**  
ClickHouse in the official Docker image may listen only on `127.0.0.1` inside the container. Port mapping then forwards to that interface, so connections from the host are not accepted.

**Fix:**

1. Add a config snippet so ClickHouse listens on all interfaces:
   - Create (or edit) **`clickhouse/config.d/listen.xml`**:
   ```xml
   <clickhouse>
       <listen_host>0.0.0.0</listen_host>
   </clickhouse>
   ```
2. Ensure `config.d` is mounted in your Compose file, e.g.:
   ```yaml
   volumes:
     - ./clickhouse/config.d:/etc/clickhouse-server/config.d:ro
   ```
3. Restart ClickHouse:  
   `docker compose up -d --force-recreate`

**Check:**  
`curl -s http://localhost:8123/ping` should return `Ok.` from the host.

---

## Issue 2: Child process exited with return code 88 (library bridge not found)

**Symptom:**  
Creating the view or running a query that uses `catboostEvaluate()` fails with:

- **Code: 302**  
- Message like: *“Child process was exited with return code 88”*  
- Stack trace involving `LibraryBridgeHelper`, `CatBoostLibraryBridgeHelper`, `startBridge`, etc.

**Cause:**  
The **official `clickhouse/clickhouse-server` Docker image does not include the `clickhouse-library-bridge` binary**. ClickHouse starts that process to talk to the CatBoost C library; when the binary is missing, the child exits with code 88.

**Check:**  
```bash
docker exec <container_name> which clickhouse-library-bridge
# If you see "not found", the image has no bridge.
```

**Fix (choose one):**

### Option A: Custom image with the library bridge (for in-DB scoring)

1. Add the ClickHouse APT repo and install `clickhouse-library-bridge` in a custom image. Example Dockerfile (**`docker/Dockerfile.clickhouse-with-bridge`**):

   ```dockerfile
   FROM clickhouse/clickhouse-server:24.8
   USER root
   RUN apt-get update \
       && apt-get install -y --no-install-recommends ca-certificates gnupg2 dirmngr wget \
       && mkdir -p /etc/apt/sources.list.d \
       && GNUPGHOME=$(mktemp -d) \
       && gpg --batch --no-default-keyring \
           --keyring /usr/share/keyrings/clickhouse-keyring.gpg \
           --keyserver hkp://keyserver.ubuntu.com:80 \
           --recv-keys 3a9ea1193a97b548be1457d48919f6bd2b48d754 \
       && rm -rf "$GNUPGHOME" \
       && echo "deb [signed-by=/usr/share/keyrings/clickhouse-keyring.gpg] https://packages.clickhouse.com/deb stable main" > /etc/apt/sources.list.d/clickhouse.list \
       && apt-get update \
       && apt-get install -y --no-install-recommends clickhouse-library-bridge \
       && rm -rf /var/lib/apt/lists/* \
       && apt-get autoremove -y --purge gnupg2 dirmngr wget || true
   USER clickhouse
   ```

2. Build and use the image:
   ```bash
   docker build -f docker/Dockerfile.clickhouse-with-bridge -t clickhouse-with-catboost:24.8 .
   docker compose -f docker-compose.yml -f docker-compose.with-bridge.yml up -d --force-recreate
   ```
   (Where the override file sets `image: clickhouse-with-catboost:24.8`.)

### Option B: Score in the application (no bridge)

- Do **not** use `catboostEvaluate()` in ClickHouse.
- Load `catboost_model.bin` in Python (or another runtime) and call `model.predict_proba()` (or equivalent) on batches.
- Use the same feature column order as in training (see Issue 3).

---

## Issue 3: “Column 0 should be numeric to make float feature” (Code 36 / 86)

**Symptom:**  
The library bridge starts, but when the view or query runs you get:

- **Code: 86** (HTTPException from the bridge) or **Code: 36** (BAD_ARGUMENTS).
- Body: *“Column 0 should be numeric to make float feature.”*

**Cause:**  
The **CatBoost C evaluation library** (`libcatboostmodel.so`) expects **float (numeric) features first**, then **categorical (string) features**, in the same order as when the model was built. If the first argument to `catboostEvaluate()` is a string column (e.g. `service_id`), the C library treats it as a float feature and fails.

**Fix:**

1. **Use a single feature order everywhere** (training, inference, and view):
   - **Numeric columns first** (e.g. `status_code`, `response_time_ms`).
   - **Categorical columns after** (e.g. `service_id`, `endpoint`, `user_agent`).

2. In your config (e.g. **`src/config.py`**), define:
   ```python
   # Numeric first, then categorical (required for ClickHouse catboostEvaluate C API)
   FEATURE_COLUMNS = ["status_code", "response_time_ms", "service_id", "endpoint", "user_agent"]
   CAT_FEATURES = ["service_id", "endpoint", "user_agent"]
   ```

3. **Train** with this order (same `FEATURE_COLUMNS` and `CAT_FEATURES`):
   ```bash
   python train.py
   ```

4. **View DDL** must pass columns in the **same order** to `catboostEvaluate()`:
   ```sql
   catboostEvaluate('/workspace/catboost_model.bin', status_code, response_time_ms, service_id, endpoint, user_agent)
   ```
   (Generate this from `FEATURE_COLUMNS` so it stays in sync.)

5. **Retrain after any feature-order change** and recreate the view; the saved model must match the order expected by the C library.

---

## CatBoost C library and model path

- ClickHouse needs the **CatBoost C evaluation library** (`libcatboostmodel.so` on Linux).  
  Download prebuilt from [CatBoost releases](https://github.com/catboost/catboost/releases) or build from source; place it where the container can read it (e.g. project root and mount as `/workspace`).
- **Architecture:** Use **aarch64** on Apple Silicon / ARM; **x86_64** on Intel/AMD Linux.
- In **`clickhouse/config.d/catboost.xml`** (or equivalent):
  ```xml
  <clickhouse>
      <catboost_lib_path>/workspace/libcatboostmodel.so</catboost_lib_path>
  </clickhouse>
  ```
- The **model path** in `catboostEvaluate()` must be the path **inside the container** (e.g. `/workspace/catboost_model.bin` if the project root is mounted at `/workspace`).

---

## Checklist: end-to-end working setup

| Step | Action |
|------|--------|
| 1 | `clickhouse/config.d/listen.xml` with `<listen_host>0.0.0.0</listen_host>` |
| 2 | ClickHouse image includes `clickhouse-library-bridge` **or** you score in the app (no bridge) |
| 3 | `libcatboostmodel.so` present and correct arch; `catboost_lib_path` set in config |
| 4 | `FEATURE_COLUMNS` = numeric first, then categorical; same order in training and in view |
| 5 | Model trained with that order: `python train.py` |
| 6 | View created with `catboostEvaluate(path, status_code, response_time_ms, service_id, endpoint, user_agent)` (or your columns in that order) |
| 7 | Query view, e.g. `SELECT timestamp, endpoint, anomaly_score FROM anomalous_events LIMIT 10` |

---

## Interpreting `anomaly_score`

`catboostEvaluate()` returns the **raw model output** (e.g. formula value), not necessarily a 0–1 probability. In this project you may see values like `9.623...` for many rows; that is expected for this model. For binary classification you can:

- Use the score as a **ranking** (higher = more likely anomaly), or  
- Apply a sigmoid in SQL or in the app to get a probability, or  
- Train/export the model for probability output if your stack supports it.

---

## Summary table

| Issue | Symptom | Fix |
|-------|---------|-----|
| Connection reset | Host cannot connect to ClickHouse | `listen_host` = `0.0.0.0` in `config.d/listen.xml` |
| Exit code 88 | “Child process was exited with return code 88” | Use custom image with `clickhouse-library-bridge` or score in app |
| Column 0 numeric | “Column 0 should be numeric to make float feature” | Put **numeric features first**, then categorical; same order in training and in `catboostEvaluate()` |
| Text features unsupported | `CANNOT_APPLY_CATBOOST_MODEL: Model contains text features but they aren't provided` | ClickHouse CatBoost bridge does **not** support text features. Train the model with **only numeric + categorical** features; do not pass raw text columns into `catboostEvaluate()`. Keep text columns (e.g. `log_payload`) for analytics or precomputed embeddings, but strip `text_features` from training and ensure the ClickHouse model `.bin` is re-trained and the container restarted. |

These steps were applied in the **cat-click-anomaly** project to get the `anomalous_events` / `anomalous_events_v2` views and in-DB scoring working; the same approach can be reused in other ClickHouse + CatBoost setups.
