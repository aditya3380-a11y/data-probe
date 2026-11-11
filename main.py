"""Command-line entry point for dataset analysis."""
import argparse
import math
from pathlib import Path

import pandas as pd

import data_generator
from data_cleaning import health_check, load_data, print_health_report
from evaluation import (compare_detectors, contamination_sweep, recall_by_type)
from ml_detector import detect_isolation_forest
from report_generator import build_suspect_table
from statistical_detector import detect_iqr
from visualize import plot_recall_by_type, plot_scatter

DEFAULT_CSV = Path("datasets/generated_data.csv")
OUTPUT_DIR = Path("outputs")


def main():
    parser = argparse.ArgumentParser(description="Data Probe - student-data anomaly checker")
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    parser.add_argument("--contamination", type=float, default=0.05,
                        help="expected share of anomalies for Isolation Forest")
    parser.add_argument("--k", type=float, default=1.5,
                        help="IQR fence multiplier")
    parser.add_argument("--x-feature", help="feature for the scatter plot x-axis")
    parser.add_argument("--y-feature", help="feature for the scatter plot y-axis")
    args = parser.parse_args()
    if not math.isfinite(args.k) or args.k <= 0:
        parser.error("--k must be greater than 0")
    if not math.isfinite(args.contamination) or not 0 < args.contamination <= 0.5:
        parser.error("--contamination must be greater than 0 and at most 0.5")
    OUTPUT_DIR.mkdir(exist_ok=True)

    if Path(args.csv) == DEFAULT_CSV and not DEFAULT_CSV.exists():
        DEFAULT_CSV.parent.mkdir(exist_ok=True)
        data_generator.build_dataset().to_csv(DEFAULT_CSV, index=False)

    df = load_data(args.csv)

    report = health_check(df)
    print_health_report(report)
    features = report["feature_cols"]
    print(f"\nColumns given to the detectors: {features}")
    if not features:
        parser.error("CSV must contain at least one numeric, non-constant feature column")

    x_feature = None
    y_feature = None
    if len(features) >= 2:
        x_feature = args.x_feature or (
            "study_hours_per_day" if "study_hours_per_day" in features else features[0]
        )
        y_feature = args.y_feature or (
            "exam_score"
            if "exam_score" in features and x_feature != "exam_score"
            else next(feature for feature in features if feature != x_feature)
        )
        if x_feature not in features:
            parser.error(f"--x-feature must be one of: {', '.join(features)}")
        if y_feature not in features:
            parser.error(f"--y-feature must be one of: {', '.join(features)}")
        if x_feature == y_feature:
            parser.error("--x-feature and --y-feature must be different")
    elif args.x_feature is not None or args.y_feature is not None:
        parser.error("A scatter plot requires at least two numeric feature columns")

    iqr_flag, col_flags, bounds = detect_iqr(df, features, k=args.k)
    if_flag, if_score = detect_isolation_forest(
        df, features, contamination=args.contamination)
    print(f"\nIQR flagged              : {int(iqr_flag.sum())} rows")
    print(f"Isolation Forest flagged : {int(if_flag.sum())} rows")
    print(f"Flagged by both          : {int((iqr_flag & if_flag).sum())} rows")

    suspects = build_suspect_table(df, features, iqr_flag, col_flags, bounds,
                                   if_flag, if_score)
    suspects.to_csv(OUTPUT_DIR / "suspicious_records.csv")
    print(f"\nSaved {len(suspects)} suspicious records to outputs/suspicious_records.csv")
    print("\n=== TOP 5 MOST SUSPICIOUS ROWS ===")
    print(suspects.head(5).to_string())

    # evaluation only possible when ground-truth labels exist
    if "anomaly_type" in df.columns:
        pd.set_option("display.float_format", "{:.2f}".format)
        print("\n=== DETECTOR COMPARISON (target: value anomalies) ===")
        print(compare_detectors(df, iqr_flag, if_flag).to_string())
        recall = recall_by_type(df, iqr_flag, if_flag)
        print("\n=== SHARE FLAGGED BY ROW TYPE ===")
        print(recall.to_string())
        print("\n=== CONTAMINATION SENSITIVITY (Isolation Forest) ===")
        print(contamination_sweep(df, features).to_string())
        plot_recall_by_type(recall, OUTPUT_DIR / "recall_by_type.png")
    else:
        print("\nNo ground-truth labels in this file, so no accuracy is reported.")

    if x_feature is not None and y_feature is not None:
        plot_scatter(df, iqr_flag, if_flag, OUTPUT_DIR / "scatter.png",
                     x=x_feature, y=y_feature)


if __name__ == "__main__":
    main()
