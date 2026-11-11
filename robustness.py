"""Is the result a lucky seed? Repeat the whole experiment on 10 different datasets."""
import pandas as pd

from data_cleaning import get_feature_columns
from data_generator import build_dataset
from evaluation import make_truth, score_detector
from ml_detector import detect_isolation_forest
from statistical_detector import detect_iqr


def run(n_seeds=10, contamination=0.05):
    """Repeat the synthetic detector evaluation across multiple random seeds."""
    rows = []
    for seed in range(n_seeds):
        df = build_dataset(seed)
        features = get_feature_columns(df)
        iqr_flag, _, _ = detect_iqr(df, features)
        if_flag, _ = detect_isolation_forest(df, features, contamination, random_state=seed)
        unusual = df["anomaly_type"] == "unusual_combo"
        rows.append({
            "IQR f1": score_detector(make_truth(df), iqr_flag)["f1"],
            "IF f1": score_detector(make_truth(df), if_flag)["f1"],
            "IQR unusual recall": iqr_flag[unusual].mean(),
            "IF unusual recall": if_flag[unusual].mean(),
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    results = run()
    print(results.agg(["mean", "std"]).round(3).T.to_string())
