"""User clustering based on usage patterns."""

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from src.analytics.queries import query


def cluster_users(n_clusters=4, db_path="output/analytics.duckdb", data=None):
    """Cluster users by their usage behavior vectors."""
    df = data.copy() if data is not None else query("""
        SELECT
            s.user_email,
            e.practice,
            e.level,
            e.location,
            COUNT(*) AS total_sessions,
            AVG(s.num_turns) AS avg_turns_per_session,
            AVG(s.num_api_calls) AS avg_api_calls_per_session,
            AVG(s.num_tool_uses) AS avg_tool_uses_per_session,
            AVG(s.total_cost) AS avg_cost_per_session,
            SUM(s.total_cost) AS total_cost,
            AVG(s.duration_sec) AS avg_duration_sec,
            SUM(s.error_count) AS total_errors
        FROM sessions s
        JOIN employees e ON s.user_email = e.email
        GROUP BY s.user_email, e.practice, e.level, e.location
    """, db_path)

    if df.empty:
        df["cluster"] = pd.Series(dtype=str)
        return df

    if len(df) == 1:
        df["cluster"] = "0"
        return df

    features = [
        "total_sessions", "avg_turns_per_session", "avg_api_calls_per_session",
        "avg_tool_uses_per_session", "avg_cost_per_session", "avg_duration_sec",
        "total_errors",
    ]
    X = df[features].fillna(0)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = KMeans(n_clusters=min(n_clusters, len(df)), random_state=42, n_init=10)
    df["cluster"] = model.fit_predict(X_scaled).astype(str)

    return df
