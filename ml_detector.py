"""Isolation Forest anomaly detection."""
import pandas as pd
from sklearn.ensemble import IsolationForest


def detect_isolation_forest(df, feature_cols, contamination=0.05,
                            n_estimators=200, random_state=42):
    """Fit on the feature columns ONLY and return (flag, score).

    flag  - bool Series, True = anomaly
    score - float Series, higher = more anomalous
    """
    X = df[feature_cols].copy()
    X = X.fillna(X.median())  # the model cannot take NaN; median is neutral

    model = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        random_state=random_state,
    )
    prediction = model.fit_predict(X)          # -1 = anomaly, 1 = normal
    score = -model.score_samples(X)            # sklearn: lower = more abnormal

    return (pd.Series(prediction == -1, index=df.index),
            pd.Series(score, index=df.index))
