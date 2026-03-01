"""Model quality test: F1-score on synthetic data meets TRD (>90%)."""

import pytest
import numpy as np
from pathlib import Path
from catboost import CatBoostClassifier
from sklearn.metrics import f1_score
from clickhouse_driver import Client

from src.config import FEATURE_COLUMNS, CAT_FEATURES, TARGET
from src.data import load_training_data
from src.schema import ensure_service_logs_table
from train import train_model

F1_MIN = 0.90


@pytest.mark.integration
def test_trained_model_f1_above_90_percent(ch_client: Client) -> None:
    """After training on data in ClickHouse, model F1 on same data (or holdout) is > 90%."""
    ensure_service_logs_table(ch_client)
    df = load_training_data(client=ch_client)
    if len(df) < 1000:
        pytest.skip("Need at least 1000 rows in service_logs; run ingest first")
    # Train/test split for a fair evaluation
    rng = np.random.default_rng(42)
    idx = rng.permutation(len(df))
    split = int(0.8 * len(df))
    train_idx, test_idx = idx[:split], idx[split:]
    X_train = df.loc[df.index[train_idx], FEATURE_COLUMNS]
    y_train = df.loc[df.index[train_idx], TARGET]
    X_test = df.loc[df.index[test_idx], FEATURE_COLUMNS]
    y_test = df.loc[df.index[test_idx], TARGET]
    model = CatBoostClassifier(
        iterations=500,
        learning_rate=0.1,
        cat_features=CAT_FEATURES,
        random_seed=42,
        verbose=0,
    )
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    f1 = f1_score(y_test, pred, zero_division=0)
    assert f1 >= F1_MIN, f"F1 {f1:.4f} below required {F1_MIN}"


@pytest.mark.integration
def test_train_saves_model_file(ch_client: Client, tmp_path: Path) -> None:
    """train_model() saves a .bin file that CatBoost can load."""
    ensure_service_logs_table(ch_client)
    df = load_training_data(client=ch_client, limit=5000)
    if len(df) < 1000:
        pytest.skip("Need at least 1000 rows; run ingest first")
    out = str(tmp_path / "catboost_model.bin")
    train_model(client=ch_client, model_path=out)
    assert Path(out).exists()
    loaded = CatBoostClassifier()
    loaded.load_model(out)
    assert loaded.feature_names_ == FEATURE_COLUMNS
