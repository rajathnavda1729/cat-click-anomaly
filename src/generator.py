"""Synthetic log generator: 80% normal, 20% anomaly traffic for service_logs; v2 with scenarios."""

from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

# Normal traffic: common endpoints and user agents
NORMAL_ENDPOINTS = ["/api/health", "/api/users", "/api/orders", "/api/products", "/api/search"]
NORMAL_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/96.0.4664.110",
]
# Anomaly: unusual user agents and 5xx-like behavior
ANOMALY_USER_AGENTS = [
    "MaliciousBot/1.0",
    "curl/7.99.99",
    "Python-requests/2.99",
    "Scanner/Probe",
    "Unknown-Weird-Client",
]
SERVICE_IDS = ["svc-a", "svc-b", "svc-c"]

# v2: log_signature grammar [SVC]:[ACTION]:[RESULT]
LOG_SIGNATURE_SVC = ["ORDER", "USER", "API", "AUTH", "PRODUCT"]
LOG_SIGNATURE_ACTION = ["CHECKOUT", "LOGIN", "FETCH", "SEARCH", "CREATE"]
LOG_SIGNATURE_RESULT_NORMAL = ["OK", "CREATED", "FOUND"]
# Rare signature for silent_failure scenario
LOG_SIGNATURE_SILENT_FAILURE = "[ORDER]:[CHECKOUT]:[EMPTY_RESULT]"

# Scenario windows (relative to base_time): festival = 10× volume in this 5-min window
FESTIVAL_BURST_START_OFFSET = timedelta(days=1, hours=12, minutes=0)  # base + 1d 12:00
FESTIVAL_BURST_MINUTES = 5
# Silent_failure: rows in this window get rare log_signature
SILENT_FAILURE_WINDOW_OFFSET = timedelta(days=2, hours=8, minutes=0)
SILENT_FAILURE_WINDOW_MINUTES = 5

# v2 column order (must match SERVICE_LOGS_V2_COLUMNS)
V2_COLUMNS = [
    "timestamp",
    "service_id",
    "endpoint",
    "status_code",
    "response_time_ms",
    "user_agent",
    "hour_of_day",
    "is_weekend",
    "throughput_velocity",
    "error_acceleration",
    "is_surge",
    "log_signature",
    "log_payload",
    "is_anomaly",
]


def _make_log_signature(rng: np.random.Generator, *, use_silent_failure: bool = False) -> str:
    if use_silent_failure:
        return LOG_SIGNATURE_SILENT_FAILURE
    svc = rng.choice(LOG_SIGNATURE_SVC)
    action = rng.choice(LOG_SIGNATURE_ACTION)
    result = rng.choice(LOG_SIGNATURE_RESULT_NORMAL)
    return f"[{svc}]:[{action}]:[{result}]"


def _make_log_payload(rng: np.random.Generator) -> str:
    rid = "".join(rng.choice(list("abcdef0123456789"), size=8))
    return f"rid={rid} msg=ok"


def _in_festival_burst(ts: datetime, base_time: datetime) -> bool:
    start = base_time + FESTIVAL_BURST_START_OFFSET
    end = start + timedelta(minutes=FESTIVAL_BURST_MINUTES)
    return start <= ts < end


def _in_silent_failure_window(ts: datetime, base_time: datetime) -> bool:
    start = base_time + SILENT_FAILURE_WINDOW_OFFSET
    end = start + timedelta(minutes=SILENT_FAILURE_WINDOW_MINUTES)
    return start <= ts < end


def generate_logs(
    n: int,
    *,
    rng: Optional[np.random.Generator] = None,
    anomaly_ratio: float = 0.20,
    base_time: Optional[datetime] = None,
    scenario: str = "normal",
) -> pd.DataFrame:
    """Generate n rows of synthetic service logs (v2 columns).

    Normal: status 200, Gaussian response times, consistent endpoints/user_agents.
    Anomaly: 5xx spikes, unusual user_agent, high latency.
    scenario:
      - "normal": default mix, v2 columns with placeholder velocity/acceleration/is_surge.
      - "festival": same mix but a 5-minute burst window has 10× row count (all normal, is_anomaly=0).
      - "silent_failure": normal volume; in a defined 5-min window, log_signature is rare [ORDER]:[CHECKOUT]:[EMPTY_RESULT], status_code=200.
    """
    if rng is None:
        rng = np.random.default_rng()
    if base_time is None:
        base_time = datetime(2024, 1, 1, 0, 0, 0)

    n_anom = int(round(n * anomaly_ratio))
    n_norm = n - n_anom

    # Timestamps: spread over ~7 days
    ts_deltas = rng.integers(0, 7 * 24 * 3600 * 1000, size=n)
    timestamps = [base_time + timedelta(milliseconds=int(d)) for d in ts_deltas]
    rng.shuffle(timestamps)

    is_anomaly = np.array([1] * n_anom + [0] * n_norm, dtype=np.uint8)
    rng.shuffle(is_anomaly)

    service_ids: list[str] = []
    endpoints: list[str] = []
    status_codes: list[int] = []
    response_times: list[int] = []
    user_agents: list[str] = []
    log_signatures: list[str] = []
    log_payloads: list[str] = []

    for i in range(n):
        ts = timestamps[i]
        in_silent_window = _in_silent_failure_window(ts, base_time)
        use_rare_sig = scenario == "silent_failure" and in_silent_window

        # Festival scenario: within the burst window, force rows to be normal
        # traffic (is_anomaly=0, status_code=200, normal latency).
        if scenario == "festival" and _in_festival_burst(ts, base_time):
            is_anomaly[i] = 0
            service_ids.append(rng.choice(SERVICE_IDS))
            endpoints.append(rng.choice(NORMAL_ENDPOINTS))
            status_codes.append(200)
            rt = int(rng.normal(150, 50))
            response_times.append(max(1, min(rt, 1000)))
            user_agents.append(rng.choice(NORMAL_USER_AGENTS))
            log_signatures.append(_make_log_signature(rng, use_silent_failure=False))
            log_payloads.append(_make_log_payload(rng))
            continue

        if is_anomaly[i]:
            service_ids.append(rng.choice(SERVICE_IDS))
            endpoints.append(rng.choice(["/api/unknown", "/admin", "/debug", "/.env"]))
            status_codes.append(int(rng.choice([500, 502, 503])))
            response_times.append(int(rng.integers(2000, 10001)))
            user_agents.append(rng.choice(ANOMALY_USER_AGENTS))
            log_signatures.append(_make_log_signature(rng, use_silent_failure=use_rare_sig))
            log_payloads.append(_make_log_payload(rng))
        else:
            service_ids.append(rng.choice(SERVICE_IDS))
            endpoints.append(rng.choice(NORMAL_ENDPOINTS))
            status_codes.append(200)
            rt = int(rng.normal(150, 50))
            response_times.append(max(1, min(rt, 1000)))
            user_agents.append(rng.choice(NORMAL_USER_AGENTS))
            log_signatures.append(_make_log_signature(rng, use_silent_failure=use_rare_sig))
            log_payloads.append(_make_log_payload(rng))

    # v2 derived columns
    hour_of_day = np.array([t.hour for t in timestamps], dtype=np.uint8)
    is_weekend = np.array([1 if t.weekday() >= 5 else 0 for t in timestamps], dtype=np.uint8)
    throughput_velocity = np.full(n, 1.0, dtype=np.float64)
    error_acceleration = np.full(n, 0.0, dtype=np.float64)
    is_surge = np.zeros(n, dtype=np.uint8)

    # Festival: 10× rows in burst window (duplicate rows that fall in the window)
    if scenario == "festival":
        burst_rows = []
        for i in range(n):
            if _in_festival_burst(timestamps[i], base_time) and is_anomaly[i] == 0:
                burst_rows.append(
                    {
                        "timestamp": timestamps[i],
                        "service_id": service_ids[i],
                        "endpoint": endpoints[i],
                        "status_code": status_codes[i],
                        "response_time_ms": response_times[i],
                        "user_agent": user_agents[i],
                        "hour_of_day": hour_of_day[i],
                        "is_weekend": is_weekend[i],
                        "log_signature": log_signatures[i],
                        "log_payload": log_payloads[i],
                    }
                )
        for _ in range(9):
            for row in burst_rows:
                timestamps.append(row["timestamp"])
                service_ids.append(row["service_id"])
                endpoints.append(row["endpoint"])
                status_codes.append(row["status_code"])
                response_times.append(row["response_time_ms"])
                user_agents.append(row["user_agent"])
                log_signatures.append(row["log_signature"])
                log_payloads.append(row["log_payload"])
        n_total = len(timestamps)
        hour_of_day = np.concatenate([hour_of_day, np.array([r["hour_of_day"] for r in burst_rows] * 9, dtype=np.uint8)])
        is_weekend = np.concatenate([is_weekend, np.array([r["is_weekend"] for r in burst_rows] * 9, dtype=np.uint8)])
        throughput_velocity = np.full(n_total, 1.0, dtype=np.float64)
        error_acceleration = np.full(n_total, 0.0, dtype=np.float64)
        is_surge = np.zeros(n_total, dtype=np.uint8)
        is_anomaly = np.concatenate([is_anomaly, np.zeros(len(burst_rows) * 9, dtype=np.uint8)])
    else:
        n_total = n

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "service_id": service_ids,
            "endpoint": endpoints,
            "status_code": np.array(status_codes, dtype=np.uint16),
            "response_time_ms": np.array(response_times, dtype=np.uint32),
            "user_agent": user_agents,
            "hour_of_day": hour_of_day,
            "is_weekend": is_weekend,
            "throughput_velocity": throughput_velocity,
            "error_acceleration": error_acceleration,
            "is_surge": is_surge,
            "log_signature": log_signatures,
            "log_payload": log_payloads,
            "is_anomaly": is_anomaly,
        },
        columns=V2_COLUMNS,
    )
