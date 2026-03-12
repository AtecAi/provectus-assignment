"""Operational Health page — for Platform / DevOps."""

import streamlit as st
import plotly.express as px

from src.analytics.queries import query
from src.dashboard.filters import build_where_clause

NO_DATA = "No data matches the current filters."


def render(filters):
    st.title("Operational Health")
    st.caption("Error rates, latency, and version distribution — Platform / DevOps view")

    w_err, p_err = build_where_clause(filters, timestamp_col="ae.timestamp", employee_alias="e",
                                      model_col="ae.model", terminal_col="ae.terminal_type")
    w_api, p_api = build_where_clause(filters, timestamp_col="a.timestamp", employee_alias="e",
                                      model_col="a.model", terminal_col="a.terminal_type")

    # Error patterns
    st.subheader("Daily Error Count by Type")
    df = query(f"""
        SELECT CAST(ae.timestamp AS DATE) AS date, ae.status_code, COUNT(*) AS error_count
        FROM api_errors ae JOIN employees e ON ae.user_email = e.email
        WHERE {w_err}
        GROUP BY date, ae.status_code ORDER BY date
    """, params=p_err)
    if not df.empty:
        fig = px.bar(df, x="date", y="error_count", color="status_code", barmode="stack",
                     labels={"error_count": "Errors", "date": "Date", "status_code": "Status Code"})
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption(NO_DATA)

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Latency by Model")
        df = query(f"""
            SELECT a.model,
                AVG(a.duration_ms) AS avg_duration_ms,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY a.duration_ms) AS p50_ms,
                PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY a.duration_ms) AS p90_ms,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY a.duration_ms) AS p99_ms,
                COUNT(*) AS num_requests
            FROM api_requests a JOIN employees e ON a.user_email = e.email
            WHERE {w_api}
            GROUP BY a.model ORDER BY avg_duration_ms DESC
        """, params=p_api)
        if not df.empty:
            fig = px.bar(df, x="model", y=["p50_ms", "p90_ms", "p99_ms"], barmode="group",
                         labels={"value": "Latency (ms)", "model": "Model", "variable": "Percentile"})
            fig.update_layout(height=400, xaxis_tickangle=-20)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption(NO_DATA)

    with col2:
        st.subheader("Avg Latency vs Request Count")
        if not df.empty:
            fig = px.scatter(df, x="num_requests", y="avg_duration_ms", size="num_requests",
                             color="model", text="model",
                             labels={"num_requests": "Request Count", "avg_duration_ms": "Avg Latency (ms)"})
            fig.update_traces(textposition="top center")
            fig.update_layout(height=400, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption(NO_DATA)

    st.markdown("---")

    st.subheader("Claude Code Version Distribution")
    df = query(f"""
        SELECT a.scope_version AS version,
            COUNT(DISTINCT a.user_email) AS user_count,
            COUNT(*) AS event_count
        FROM api_requests a JOIN employees e ON a.user_email = e.email
        WHERE {w_api}
        GROUP BY a.scope_version ORDER BY user_count DESC, version
        LIMIT 15
    """, params=p_api)
    if not df.empty:
        fig = px.bar(df, x="version", y="user_count", labels={"user_count": "Users", "version": "Version"})
        fig.update_layout(height=400, xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption(NO_DATA)
