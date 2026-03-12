"""Advanced Analytics page — ML forecasting, anomaly detection, clustering."""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from src.analytics.queries import query
from src.dashboard.filters import build_session_model_filter, build_where_clause

NO_DATA = "No data matches the current filters."


def _load_filtered_daily_cost(filters):
    """Load daily cost history using the same global dashboard filters."""
    w, p = build_where_clause(
        filters,
        timestamp_col="a.timestamp",
        employee_alias="e",
        model_col="a.model",
        terminal_col="a.terminal_type",
    )
    return query(f"""
        SELECT
            CAST(a.timestamp AS DATE) AS date,
            SUM(a.cost_usd) AS daily_cost
        FROM api_requests a
        JOIN employees e ON a.user_email = e.email
        WHERE {w}
        GROUP BY date
        ORDER BY date
    """, params=p)


def _load_filtered_sessions(filters):
    """Load session-level features for anomaly detection with global filters applied."""
    w, p = build_where_clause(filters, timestamp_col="s.start_time", employee_alias="e")
    sess_sub, sess_params = build_session_model_filter(filters)
    if sess_sub:
        w += f" AND s.session_id IN ({sess_sub})"
        p.extend(sess_params)

    return query(f"""
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
        WHERE {w}
    """, params=p)


def _load_filtered_user_features(filters):
    """Load per-user aggregates for clustering with global filters applied."""
    w, p = build_where_clause(filters, timestamp_col="s.start_time", employee_alias="e")
    sess_sub, sess_params = build_session_model_filter(filters)
    if sess_sub:
        w += f" AND s.session_id IN ({sess_sub})"
        p.extend(sess_params)

    return query(f"""
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
        WHERE {w}
        GROUP BY s.user_email, e.practice, e.level, e.location
    """, params=p)


def render(filters):
    st.title("Advanced Analytics")
    st.caption("Predictive analytics, anomaly detection, and user clustering")

    # Forecast uses the filtered history, then projects forward from that subset.
    st.subheader("Cost Trend & Forecast")
    try:
        from src.ml.forecasting import forecast_daily_cost
        df_forecast = forecast_daily_cost(data=_load_filtered_daily_cost(filters))
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_forecast["date"], y=df_forecast["actual"],
            mode="lines", name="Actual",
        ))
        fig.add_trace(go.Scatter(
            x=df_forecast["date"], y=df_forecast["forecast"],
            mode="lines", name="Forecast", line=dict(dash="dash"),
        ))
        if "lower" in df_forecast.columns and "upper" in df_forecast.columns:
            fig.add_trace(go.Scatter(
                x=df_forecast["date"].tolist() + df_forecast["date"].tolist()[::-1],
                y=df_forecast["upper"].tolist() + df_forecast["lower"].tolist()[::-1],
                fill="toself", fillcolor="rgba(0,100,200,0.1)",
                line=dict(color="rgba(0,0,0,0)"), name="Confidence Interval",
            ))
        fig.update_layout(height=400, yaxis_title="Daily Cost (USD)")
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.warning(f"Forecasting unavailable: {e}")

    st.markdown("---")

    # Anomaly detection — filtered by date and employee dimensions
    st.subheader("Session Anomalies")
    try:
        from src.ml.anomaly import detect_session_anomalies
        df_anomalies = detect_session_anomalies(data=_load_filtered_sessions(filters))

        if not df_anomalies.empty:
            n_anomalies = df_anomalies["is_anomaly"].sum()
            st.metric("Anomalous Sessions", f"{n_anomalies} / {len(df_anomalies)}")

            fig = px.scatter(
                df_anomalies, x="total_cost", y="num_turns",
                color="is_anomaly",
                color_discrete_map={True: "#e74c3c", False: "#3498db"},
                labels={"total_cost": "Session Cost (USD)", "num_turns": "Turns", "is_anomaly": "Anomaly"},
                opacity=0.6,
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)

            if n_anomalies > 0:
                st.subheader("Top Anomalous Sessions")
                anomalies = df_anomalies[df_anomalies["is_anomaly"]].sort_values("total_cost", ascending=False)
                st.dataframe(anomalies.head(10), use_container_width=True)
        else:
            st.caption(NO_DATA)
    except Exception as e:
        st.warning(f"Anomaly detection unavailable: {e}")

    st.markdown("---")

    # User clustering — filtered
    st.subheader("User Behavior Clusters")
    try:
        from src.ml.clustering import cluster_users
        df_clusters = cluster_users(data=_load_filtered_user_features(filters))

        if not df_clusters.empty:
            fig = px.scatter(
                df_clusters, x="avg_cost_per_session", y="avg_turns_per_session",
                color="cluster", symbol="practice",
                labels={
                    "avg_cost_per_session": "Avg Cost/Session (USD)",
                    "avg_turns_per_session": "Avg Turns/Session",
                    "cluster": "Cluster",
                },
                hover_data=["user_email", "practice", "level", "total_sessions"],
            )
            fig.update_layout(height=500)
            st.plotly_chart(fig, use_container_width=True)

            st.subheader("Cluster Summary")
            summary = df_clusters.groupby("cluster").agg({
                "user_email": "count",
                "avg_cost_per_session": "mean",
                "avg_turns_per_session": "mean",
                "total_sessions": "mean",
            }).rename(columns={"user_email": "num_users"}).round(3)
            st.dataframe(summary, use_container_width=True)
        else:
            st.caption(NO_DATA)
    except Exception as e:
        st.warning(f"Clustering unavailable: {e}")
