"""Anomaly detection on sessions using Isolation Forest."""

import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from src.analytics.queries import query


def detect_session_anomalies(contamination=0.05, db_path="output/analytics.duckdb", data=None):
    """Flag anomalous sessions based on cost, turns, api calls, tool uses, errors."""
    df = data.copy() if data is not None else query("""
        SELECT
            s.session_id,
            s.user_email,
            s.start_time,
            s.num_turns,
            s.num_api_calls,
            s.num_tool_uses,
            s.total_cost,
            s.duration_sec,
            s.error_count,
            e.practice,
            e.level,
            e.location
        FROM sessions s
        JOIN employees e ON s.user_email = e.email
    """, db_path)

    if df.empty:
        df["is_anomaly"] = pd.Series(dtype=bool)
        df["anomaly_score"] = pd.Series(dtype=float)
        return df

    if len(df) < 2:
        df["is_anomaly"] = False
        df["anomaly_score"] = 0.0
        return df

    features = ["num_turns", "num_api_calls", "num_tool_uses", "total_cost", "duration_sec", "error_count"]
    X = df[features].fillna(0)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(
        contamination=min(max(contamination, 0.001), 0.5),
        random_state=42,
        n_estimators=100,
    )
    predictions = model.fit_predict(X_scaled)

    df["is_anomaly"] = predictions == -1
    df["anomaly_score"] = model.decision_function(X_scaled)

    return df
