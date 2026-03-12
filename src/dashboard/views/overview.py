"""Overview page — KPIs and daily activity."""

import streamlit as st
import plotly.express as px

from src.analytics.queries import query
from src.dashboard.filters import build_where_clause, build_session_model_filter

NO_DATA = "No data matches the current filters."


def render(filters):
    st.title("Overview")
    st.caption("High-level metrics across all Claude Code usage")

    w, p = build_where_clause(filters, timestamp_col="s.start_time", employee_alias="e")
    # sessions lacks model/terminal columns — apply via session subquery
    sess_sub, sess_params = build_session_model_filter(filters)
    if sess_sub:
        w += f" AND s.session_id IN ({sess_sub})"
        p.extend(sess_params)

    kpi_df = query(f"""
        SELECT
            COALESCE(SUM(s.total_cost), 0) AS total_cost,
            COUNT(*) AS total_sessions,
            COUNT(DISTINCT s.user_email) AS active_users,
            COALESCE(SUM(s.error_count), 0) AS total_errors,
            COALESCE(SUM(s.num_api_calls), 0) AS total_api_calls
        FROM sessions s
        JOIN employees e ON s.user_email = e.email
        WHERE {w}
    """, params=p)

    if kpi_df.empty or kpi_df.iloc[0]["total_sessions"] == 0:
        cols = st.columns(5)
        cols[0].metric("Total Cost", "$0.00")
        cols[1].metric("Sessions", "0")
        cols[2].metric("Active Users", "0")
        cols[3].metric("API Calls", "0")
        cols[4].metric("Error Rate", "0.00%")
        st.caption(NO_DATA)
    else:
        kpis = kpi_df.iloc[0]
        error_rate = (kpis["total_errors"] / kpis["total_api_calls"] * 100) if kpis["total_api_calls"] > 0 else 0
        cols = st.columns(5)
        cols[0].metric("Total Cost", f"${kpis['total_cost']:,.2f}")
        cols[1].metric("Sessions", f"{int(kpis['total_sessions']):,}")
        cols[2].metric("Active Users", f"{int(kpis['active_users']):,}")
        cols[3].metric("API Calls", f"{int(kpis['total_api_calls']):,}")
        cols[4].metric("Error Rate", f"{error_rate:.2f}%")

    st.markdown("---")

    w_prompt, p_prompt = build_where_clause(filters, timestamp_col="up.timestamp", employee_alias="e")
    if sess_sub:
        w_prompt += f" AND up.session_id IN ({sess_sub})"
        p_prompt.extend(list(sess_params))
    w_api, p_api = build_where_clause(filters, timestamp_col="a.timestamp", employee_alias="e",
                                      model_col="a.model", terminal_col="a.terminal_type")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Daily User Activity")
        df = query(f"""
            SELECT
                CAST(up.timestamp AS DATE) AS date,
                COUNT(*) AS prompt_count,
                COUNT(DISTINCT up.session_id) AS session_count,
                COUNT(DISTINCT up.user_email) AS active_users
            FROM user_prompts up
            JOIN employees e ON up.user_email = e.email
            WHERE {w_prompt}
            GROUP BY date ORDER BY date
        """, params=p_prompt)
        if not df.empty:
            fig = px.line(
                df, x="date", y=["prompt_count", "session_count", "active_users"],
                labels={"value": "Count", "date": "Date", "variable": "Metric"},
            )
            fig.update_layout(hovermode="x unified", height=400)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption(NO_DATA)

    with col2:
        st.subheader("Daily Cost Trend")
        df = query(f"""
            SELECT CAST(a.timestamp AS DATE) AS date, SUM(a.cost_usd) AS daily_cost
            FROM api_requests a
            JOIN employees e ON a.user_email = e.email
            WHERE {w_api}
            GROUP BY date ORDER BY date
        """, params=p_api)
        if not df.empty:
            fig = px.bar(df, x="date", y="daily_cost", labels={"daily_cost": "Cost (USD)", "date": "Date"})
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption(NO_DATA)

    st.markdown("---")

    # Data Quality
    st.subheader("Data Quality")
    try:
        dq = query("SELECT table_name, field_name, total_rows, null_count, parse_failure_count, is_optional FROM data_quality ORDER BY table_name, field_name")
        if not dq.empty:
            dq["null_pct"] = (dq["null_count"] / dq["total_rows"] * 100).round(2)
            dq["parse_fail_pct"] = (dq["parse_failure_count"] / dq["total_rows"] * 100).round(2)

            total_parse_failures = int(dq["parse_failure_count"].sum())
            # Required fields with any NULLs, or any field with parse failures
            fields_with_issues = int(
                ((~dq["is_optional"] & (dq["null_count"] > 0)) | (dq["parse_failure_count"] > 0)).sum()
            )

            cols = st.columns(3)
            cols[0].metric("Fields Monitored", len(dq))
            cols[1].metric("Parse Failures", total_parse_failures)
            cols[2].metric("Fields with Issues", fields_with_issues)

            st.dataframe(
                dq[["table_name", "field_name", "total_rows", "null_count", "null_pct",
                    "parse_failure_count", "parse_fail_pct", "is_optional"]],
                use_container_width=True,
            )
        else:
            st.info("No data quality metrics available. Re-run ingestion.")
    except Exception:
        st.info("Data quality table not available. Re-run ingestion.")
