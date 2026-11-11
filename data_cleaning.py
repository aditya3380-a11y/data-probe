"""CSV loading and data-quality checks."""
import pandas as pd

# Ground-truth columns from the synthetic data. They must never be model inputs.
LABEL_COLS = ["is_anomaly", "anomaly_type"]

# Domain rules for the student dataset: (minimum, maximum) possible value.
VALID_RANGES = {
    "study_hours_per_day": (0, 24),
    "attendance_percent": (0, 100),
    "assignment_completion_percent": (0, 100),
    "sleep_hours": (0, 24),
    "exam_score": (0, 100),
    "age": (15, 22),
    "Medu": (0, 4),
    "Fedu": (0, 4),
    "traveltime": (1, 4),
    "studytime": (1, 4),
    "failures": (0, 3),
    "famrel": (1, 5),
    "freetime": (1, 5),
    "goout": (1, 5),
    "Dalc": (1, 5),
    "Walc": (1, 5),
    "health": (1, 5),
    "G1": (0, 20),
    "G2": (0, 20),
    "G3": (0, 20),
}


def load_data(path):
    """Read a CSV; sep=None lets pandas detect ',' or ';' (UCI files use ';')."""
    return pd.read_csv(path, sep=None, engine="python")


def get_feature_columns(df):
    """Numeric, non-constant columns that are not ground-truth labels."""
    numeric = df.select_dtypes(include="number").columns
    return [c for c in numeric if c not in LABEL_COLS and df[c].nunique() > 1]


def numbers_stored_as_text(df):
    """Text columns where at least 90% of values are actually numbers."""
    suspicious = []
    text_columns = [
        col for col in df.columns
        if pd.api.types.is_string_dtype(df[col].dtype)
    ]
    for col in text_columns:
        converted = pd.to_numeric(df[col], errors="coerce")
        if converted.notna().mean() >= 0.9:
            suspicious.append(col)
    return suspicious


def find_invalid_values(df, rules=VALID_RANGES):
    """Boolean Series: True where a row breaks any domain rule."""
    broken = pd.Series(False, index=df.index)
    for col, (low, high) in rules.items():
        if col in df.columns:
            values = pd.to_numeric(df[col], errors="coerce")
            broken |= values.notna() & ((values < low) | (values > high))
    return broken


def find_duplicates(df, feature_cols):
    """True for the 2nd, 3rd... copy of a row (labels are ignored on purpose)."""
    return df.duplicated(subset=feature_cols, keep="first")


def health_check(df):
    """Summarize missing data, duplicates, constants, and range violations."""
    feature_cols = get_feature_columns(df)
    all_cols = [c for c in df.columns if c not in LABEL_COLS]
    rule_columns = [c for c in VALID_RANGES if c in df.columns]
    return {
        "n_rows": len(df),
        "n_columns": len(all_cols),
        "feature_cols": feature_cols,
        "rule_columns": rule_columns,
        "missing_per_column": df[all_cols].isnull().sum(),
        "rows_with_missing": int(df[all_cols].isnull().any(axis=1).sum()),
        "n_duplicates": int(find_duplicates(df, all_cols).sum()),
        "constant_columns": [c for c in all_cols if df[c].nunique() <= 1],
        "numbers_stored_as_text": numbers_stored_as_text(df[all_cols]),
        "n_rule_violations": int(find_invalid_values(df).sum()),
        "describe": df[feature_cols].describe().round(2),
    }


def print_health_report(report):
    """Print the health-check summary in a human-readable format."""
    print("=== DATA HEALTH CHECK ===")
    print(f"Rows: {report['n_rows']}   Columns: {report['n_columns']}")
    print(f"Rows with missing values : {report['rows_with_missing']}")
    print(f"Duplicate rows           : {report['n_duplicates']}")
    if report["rule_columns"]:
        print(f"Rows breaking range rules: {report['n_rule_violations']}")
        print(f"Range rules checked      : {report['rule_columns']}")
    else:
        print("Rows breaking range rules: not checked (no matching rules)")
    print(f"Constant columns         : {report['constant_columns'] or 'none'}")
    print(f"Numbers stored as text   : {report['numbers_stored_as_text'] or 'none'}")
    print("Missing values per column:")
    print(report["missing_per_column"].to_string())
