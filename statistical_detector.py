"""IQR-based statistical outlier detection."""
import numpy as np
import pandas as pd


def iqr_bounds(values, k=1.5):
    """Return (lower, upper) fences: Q1 - k*IQR and Q3 + k*IQR."""
    q1, q3 = np.percentile(values, [25, 75])
    iqr = q3 - q1
    return q1 - k * iqr, q3 + k * iqr


def detect_iqr(df, feature_cols, k=1.5):
    """Check every column on its own.

    Returns:
        row_flag - Series, True if ANY column of that row is outside its fences
        col_flags - DataFrame, which column(s) caused the flag
        bounds   - dict {column: (lower, upper)}
    """
    col_flags = pd.DataFrame(False, index=df.index, columns=feature_cols)
    bounds = {}
    for col in feature_cols:
        low, high = iqr_bounds(df[col].dropna().to_numpy(), k)
        col_flags[col] = (df[col] < low) | (df[col] > high)  # NaN compares False
        bounds[col] = (low, high)
    return col_flags.any(axis=1), col_flags, bounds
