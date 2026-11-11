"""Generate a controlled synthetic student dataset with known, labelled problems."""
from pathlib import Path

import numpy as np
import pandas as pd

RANDOM_SEED = 42
N_NORMAL = 2000
N_PER_TYPE = 40  # rows injected for each problem type
OUTPUT_PATH = Path("datasets/generated_data.csv")


def make_normal(rng, n):
    """Realistic students: columns are correlated, like real data."""
    study = np.clip(rng.normal(4, 1.5, n), 0.5, 10)
    attendance = np.clip(75 + 3 * (study - 4) + rng.normal(0, 8, n), 40, 100)
    assignment = np.clip(0.6 * attendance + 30 + rng.normal(0, 8, n), 20, 100)
    sleep = np.clip(rng.normal(7, 1, n), 4, 10)
    exam = np.clip(
        20 + 4 * study + 0.3 * attendance + 0.2 * assignment + rng.normal(0, 5, n),
        0, 100,
    )
    return pd.DataFrame({
        "study_hours_per_day": study,
        "attendance_percent": attendance,
        "assignment_completion_percent": assignment,
        "sleep_hours": sleep,
        "exam_score": exam,
    }).round(1)


def make_extreme(rng, n):
    """Normal rows with ONE impossible value (e.g. 120% attendance)."""
    df = make_normal(rng, n)
    impossible = {
        "study_hours_per_day": (18, 24),
        "attendance_percent": (105, 150),
        "sleep_hours": (14, 20),
        "exam_score": (105, 150),
    }
    for i, col in enumerate(rng.choice(list(impossible), n)):
        low, high = impossible[col]
        df.at[i, col] = round(rng.uniform(low, high), 1)
    return df


def make_inconsistent(rng, n):
    """Barely studies and rarely attends, yet scores near the top."""
    df = make_normal(rng, n)
    df["study_hours_per_day"] = rng.uniform(0.5, 1.5, n).round(1)
    df["attendance_percent"] = rng.uniform(35, 55, n).round(1)
    df["assignment_completion_percent"] = rng.uniform(25, 45, n).round(1)
    df["exam_score"] = rng.uniform(88, 99, n).round(1)
    return df


def make_unusual(rng, n):
    """Every value is individually plausible; the COMBINATION is not.
    Studies a lot, attends, submits everything... and still scores low."""
    df = make_normal(rng, n)
    df["study_hours_per_day"] = rng.uniform(6.5, 8.5, n).round(1)
    df["attendance_percent"] = rng.uniform(85, 98, n).round(1)
    df["assignment_completion_percent"] = rng.uniform(80, 95, n).round(1)
    df["exam_score"] = rng.uniform(52, 60, n).round(1)
    return df


def make_missing(rng, n):
    """Normal rows where 1-2 values are blanked out."""
    df = make_normal(rng, n)
    cols = list(df.columns)
    for i in range(n):
        for col in rng.choice(cols, size=rng.integers(1, 3), replace=False):
            df.at[i, col] = np.nan
    return df


def build_dataset(seed=RANDOM_SEED):
    """Build the shuffled synthetic dataset with ground-truth anomaly labels."""
    rng = np.random.default_rng(seed)

    normal = make_normal(rng, N_NORMAL)
    normal["anomaly_type"] = "normal"

    parts = [normal]
    for name, maker in [
        ("extreme_value", make_extreme),
        ("inconsistent_combo", make_inconsistent),
        ("unusual_combo", make_unusual),
        ("missing_value", make_missing),
    ]:
        part = maker(rng, N_PER_TYPE)
        part["anomaly_type"] = name
        parts.append(part)

    # exact copies of existing normal rows
    dup = normal.sample(N_PER_TYPE, random_state=seed).copy()
    dup["anomaly_type"] = "duplicate"
    parts.append(dup)

    df = pd.concat(parts, ignore_index=True)
    df["is_anomaly"] = (df["anomaly_type"] != "normal").astype(int)
    # shuffle so the file does not reveal which rows are injected
    return df.sample(frac=1, random_state=seed).reset_index(drop=True)


if __name__ == "__main__":
    data = build_dataset()
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    data.to_csv(OUTPUT_PATH, index=False)
    print(f"Saved {len(data)} rows to {OUTPUT_PATH}")
    print(data["anomaly_type"].value_counts().to_string())
