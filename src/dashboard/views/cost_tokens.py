"""Cost & Tokens page — for Engineering Managers."""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from src.analytics.queries import query
from src.dashboard.filters import build_where_clause

NO_DATA = "No data matches the current filters."


def render(filters):
    st.title("Cost & Tokens")
    st.caption("Cost control and token consumption analysis — Engineering Manager view")

    w, p = build_where_clause(filters, timestamp_col="a.timestamp", employee_alias="e",
                              model_col="a.model", terminal_col="a.terminal_type")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Total Cost by Practice")
        df = query(f"""
            SELECT e.practice, SUM(a.cost_usd) AS total_cost, COUNT(*) AS num_requests
            FROM api_requests a JOIN employees e ON a.user_email = e.email
            WHERE {w} GROUP BY e.practice ORDER BY total_cost DESC
        """, params=p)
        if not df.empty:
            fig = px.bar(df, x="practice", y="total_cost", color="practice",
                         labels={"total_cost": "Cost (USD)", "practice": "Practice"})
            fig.update_layout(showlegend=False, height=400)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption(NO_DATA)

    with col2:
        st.subheader("Cost by Model")
        df = query(f"""
            SELECT a.model, SUM(a.cost_usd) AS total_cost
            FROM api_requests a JOIN employees e ON a.user_email = e.email
            WHERE {w} GROUP BY a.model ORDER BY total_cost DESC
        """, params=p)
        if not df.empty:
            fig = px.pie(df, values="total_cost", names="model", hole=0.4)
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption(NO_DATA)

    st.markdown("---")

    st.subheader("Token Consumption by Practice")
    df = query(f"""
        SELECT e.practice,
            SUM(a.input_tokens) AS total_input_tokens,
            SUM(a.output_tokens) AS total_output_tokens,
            SUM(a.cache_read_tokens) AS total_cache_read_tokens,
            SUM(a.cache_creation_tokens) AS total_cache_creation_tokens
        FROM api_requests a JOIN employees e ON a.user_email = e.email
        WHERE {w} GROUP BY e.practice ORDER BY total_input_tokens DESC
    """, params=p)
    if not df.empty:
        fig = go.Figure()
        for col in ["total_input_tokens", "total_output_tokens", "total_cache_read_tokens", "total_cache_creation_tokens"]:
            label = col.replace("total_", "").replace("_", " ").title()
            fig.add_trace(go.Bar(name=label, x=df["practice"], y=df[col]))
        fig.update_layout(barmode="group", height=450, yaxis_title="Tokens")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption(NO_DATA)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Token Consumption by Seniority")
        df = query(f"""
            SELECT e.level,
                SUM(a.input_tokens) AS total_input_tokens,
                SUM(a.output_tokens) AS total_output_tokens
            FROM api_requests a JOIN employees e ON a.user_email = e.email
            WHERE {w} GROUP BY e.level ORDER BY e.level
        """, params=p)
        if not df.empty:
            fig = go.Figure()
            fig.add_trace(go.Bar(name="Input Tokens", x=df["level"], y=df["total_input_tokens"]))
            fig.add_trace(go.Bar(name="Output Tokens", x=df["level"], y=df["total_output_tokens"]))
            fig.update_layout(barmode="stack", height=400, yaxis_title="Tokens")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption(NO_DATA)

    with col2:
        st.subheader("Cost by Practice & Level")
        df = query(f"""
            SELECT e.practice, e.level, SUM(a.cost_usd) AS total_cost
            FROM api_requests a JOIN employees e ON a.user_email = e.email
            WHERE {w} GROUP BY e.practice, e.level ORDER BY e.practice, e.level
        """, params=p)
        if not df.empty:
            fig = px.treemap(df, path=["practice", "level"], values="total_cost",
                             color="total_cost", color_continuous_scale="Reds")
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption(NO_DATA)

    st.subheader("Daily Cost Trend")
    df = query(f"""
        SELECT CAST(a.timestamp AS DATE) AS date, SUM(a.cost_usd) AS daily_cost
        FROM api_requests a JOIN employees e ON a.user_email = e.email
        WHERE {w} GROUP BY date ORDER BY date
    """, params=p)
    if not df.empty:
        fig = px.area(df, x="date", y="daily_cost", labels={"daily_cost": "Cost (USD)", "date": "Date"})
        fig.update_layout(height=350)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption(NO_DATA)
