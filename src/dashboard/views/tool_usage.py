"""Tool Usage page — for Platform / DevOps."""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from src.analytics.queries import query
from src.dashboard.filters import build_where_clause, build_session_model_filter

NO_DATA = "No data matches the current filters."


def render(filters):
    st.title("Tool Usage")
    st.caption("Tool frequency, success rates, and permission patterns — Platform / DevOps view")

    w_td, p_td = build_where_clause(filters, timestamp_col="td.timestamp", employee_alias="e")
    w_tr, p_tr = build_where_clause(filters, timestamp_col="tr.timestamp", employee_alias="e")

    # Apply model/terminal filters via session subquery (these tables lack those columns)
    sess_sub, sess_params = build_session_model_filter(filters)
    if sess_sub:
        w_td += f" AND td.session_id IN ({sess_sub})"
        p_td.extend(sess_params)
        w_tr += f" AND tr.session_id IN ({sess_sub})"
        p_tr.extend(list(sess_params))

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Tool Usage Frequency")
        df = query(f"""
            SELECT td.tool_name, COUNT(*) AS usage_count,
                SUM(CASE WHEN td.decision = 'accept' THEN 1 ELSE 0 END) AS accepted,
                SUM(CASE WHEN td.decision = 'reject' THEN 1 ELSE 0 END) AS rejected
            FROM tool_decisions td JOIN employees e ON td.user_email = e.email
            WHERE {w_td} GROUP BY td.tool_name ORDER BY usage_count DESC
        """, params=p_td)
        if not df.empty:
            fig = px.bar(df, x="tool_name", y="usage_count", color="tool_name",
                         labels={"usage_count": "Usage Count", "tool_name": "Tool"})
            fig.update_layout(showlegend=False, height=400, xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption(NO_DATA)

    with col2:
        st.subheader("Accept / Reject by Tool")
        if not df.empty:
            fig = go.Figure()
            fig.add_trace(go.Bar(name="Accepted", x=df["tool_name"], y=df["accepted"], marker_color="#2ecc71"))
            fig.add_trace(go.Bar(name="Rejected", x=df["tool_name"], y=df["rejected"], marker_color="#e74c3c"))
            fig.update_layout(barmode="stack", height=400, xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption(NO_DATA)

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Tool Success Rates")
        df = query(f"""
            SELECT tr.tool_name, COUNT(*) AS total_executions,
                COUNT(tr.success) AS known_outcomes,
                SUM(CASE WHEN tr.success THEN 1 ELSE 0 END) AS successes,
                ROUND(SUM(CASE WHEN tr.success THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(tr.success), 0), 2) AS success_rate,
                AVG(tr.duration_ms) AS avg_duration_ms
            FROM tool_results tr JOIN employees e ON tr.user_email = e.email
            WHERE {w_tr} GROUP BY tr.tool_name ORDER BY success_rate ASC
        """, params=p_tr)
        if not df.empty:
            fig = px.bar(df, x="tool_name", y="success_rate", color="success_rate",
                         color_continuous_scale="RdYlGn",
                         labels={"success_rate": "Success Rate (%)", "tool_name": "Tool"})
            fig.update_layout(showlegend=False, height=400, xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption(NO_DATA)

    with col2:
        st.subheader("Avg Execution Duration by Tool")
        if not df.empty:
            df_fast = df[df["avg_duration_ms"] < 50000].copy()
            fig = px.bar(df_fast, x="tool_name", y="avg_duration_ms",
                         labels={"avg_duration_ms": "Avg Duration (ms)", "tool_name": "Tool"})
            fig.update_layout(height=400, xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption(NO_DATA)

    st.subheader("Tool Rejection Rate by Seniority")
    df = query(f"""
        SELECT td.tool_name, e.level,
            SUM(CASE WHEN td.decision = 'reject' THEN 1 ELSE 0 END) AS rejected,
            COUNT(*) AS total,
            ROUND(SUM(CASE WHEN td.decision = 'reject' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS reject_pct
        FROM tool_decisions td JOIN employees e ON td.user_email = e.email
        WHERE {w_td} GROUP BY td.tool_name, e.level ORDER BY td.tool_name, e.level
    """, params=p_td)
    if not df.empty:
        pivot = df.pivot_table(index="tool_name", columns="level", values="reject_pct", fill_value=0)
        level_order = [f"L{i}" for i in range(1, 11)]
        pivot = pivot.reindex(columns=[c for c in level_order if c in pivot.columns])
        fig = px.imshow(pivot.values, x=pivot.columns.tolist(), y=pivot.index.tolist(),
                        color_continuous_scale="Reds", labels={"color": "Reject %"}, aspect="auto")
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption(NO_DATA)
