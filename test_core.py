"""Quick sanity tests. Run with:  python test_core.py"""
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from data_cleaning import (LABEL_COLS, find_duplicates, get_feature_columns,
                           health_check, load_data)
from data_generator import build_dataset
from ml_detector import detect_isolation_forest
from statistical_detector import detect_iqr, iqr_bounds


def test_iqr_flags_obvious_outlier():
    """Check that the IQR fences exclude a clear extreme value."""
    low, high = iqr_bounds(np.array([1, 2, 3, 4, 5, 100]))
    assert 100 > high and low < 1


def test_labels_never_become_features():
    """Ensure synthetic ground-truth columns are excluded from model inputs."""
    df = build_dataset()
    features = get_feature_columns(df)
    assert not set(features) & set(LABEL_COLS)


def test_dataset_counts():
    """Check the expected synthetic row and normal-row counts."""
    df = build_dataset()
    assert len(df) == 2200
    assert (df["anomaly_type"] == "normal").sum() == 2000


def test_duplicates_found_exactly():
    """Check that the health helper finds each injected duplicate once."""
    df = build_dataset()
    all_cols = [c for c in df.columns if c not in LABEL_COLS]
    assert find_duplicates(df, all_cols).sum() == 40


def test_detectors_handle_missing_values():
    """Ensure both detectors return one flag per row despite missing values."""
    df = build_dataset()
    features = get_feature_columns(df)
    flag, score = detect_isolation_forest(df, features)
    assert len(flag) == len(df) and score.notna().all()
    iqr_flag, _, _ = detect_iqr(df, features)
    assert iqr_flag.dtype == bool


def test_isolation_forest_is_reproducible():
    """Ensure a fixed random seed produces repeatable Isolation Forest flags."""
    df = build_dataset()
    features = get_feature_columns(df)
    a, _ = detect_isolation_forest(df, features, random_state=1)
    b, _ = detect_isolation_forest(df, features, random_state=1)
    assert a.equals(b)


def test_load_data_reads_semicolon_csv():
    """Check that CSV loading detects the semicolon delimiter used by UCI."""
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "student.csv"
        path.write_text("school;sex;G1\nGP;F;10\n", encoding="utf-8")
        df = load_data(path)

    assert df.columns.tolist() == ["school", "sex", "G1"]
    assert df.loc[0, "G1"] == 10


def test_health_check_applies_uci_ranges():
    """Check that the UCI student columns get their domain-range checks."""
    df = pd.DataFrame({"age": ["16", "25", "unknown"], "G1": [10, 21, 5]})

    report = health_check(df)

    assert report["rule_columns"] == ["age", "G1"]
    assert report["n_rule_violations"] == 1


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
