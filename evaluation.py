"""Compare detectors against the ground-truth labels of the synthetic dataset."""
import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

from ml_detector import detect_isolation_forest

# Problems that detectors are supposed to find from VALUES.
# Missing values and exact duplicates belong to the health check instead.
VALUE_ANOMALY_TYPES = ["extreme_value", "inconsistent_combo", "unusual_combo"]


def make_truth(df):
    """Select synthetic value anomalies, excluding missing rows and duplicates."""
    return df["anomaly_type"].isin(VALUE_ANOMALY_TYPES)


def score_detector(y_true, y_pred):
    """Calculate classification metrics and confusion-matrix counts."""
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[False, True]).ravel()
    return {
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall": recall_score(y_true, y_pred, zero_division=0),
        "f1": f1_score(y_true, y_pred, zero_division=0),
        "TP": tp, "FP": fp, "FN": fn, "TN": tn,
    }


def compare_detectors(df, iqr_flag, if_flag):
    """Compare detector combinations against synthetic target labels."""
    y_true = make_truth(df)
    candidates = {
        "IQR": iqr_flag,
        "Isolation Forest": if_flag,
        "Either (OR)": iqr_flag | if_flag,
        "Both (AND)": iqr_flag & if_flag,
    }
    rows = {name: score_detector(y_true, flag) for name, flag in candidates.items()}
    return pd.DataFrame(rows).T


def recall_by_type(df, iqr_flag, if_flag):
    """Calculate the share of each anomaly type flagged by each detector."""
    out = pd.DataFrame({
        "IQR": iqr_flag.groupby(df["anomaly_type"]).mean(),
        "Isolation Forest": if_flag.groupby(df["anomaly_type"]).mean(),
    })
    return out.loc[["normal"] + VALUE_ANOMALY_TYPES + ["missing_value", "duplicate"]]


def contamination_sweep(df, feature_cols, values=(0.02, 0.04, 0.06, 0.08, 0.10)):
    """How sensitive is Isolation Forest to the contamination setting?"""
    y_true = make_truth(df)
    rows = {}
    for c in values:
        flag, _ = detect_isolation_forest(df, feature_cols, contamination=c)
        rows[c] = score_detector(y_true, flag)
    return pd.DataFrame(rows).T[["precision", "recall", "f1"]]
