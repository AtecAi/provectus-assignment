"""User Behavior page — for Individual Developers."""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from src.analytics.queries import query
from src.dashboard.filters import build_where_clause, build_session_model_filter

NO_DATA = "No data matches the current filters."


def render(filters):
    st.title("User Behavior")
    st.caption("Session patterns, prompt habits, and IDE preferences — Individual Developer view")

    w_prompt, p_prompt = build_where_clause(filters, timestamp_col="up.timestamp", employee_alias="e")
    w_session, p_session = build_where_clause(filters, timestamp_col="s.start_time", employee_alias="e")
    w_api, p_api = build_where_clause(filters, timestamp_col="a.timestamp", employee_alias="e",
                                      model_col="a.model", terminal_col="a.terminal_type")

    # Apply model/terminal filters via session subquery (prompts/sessions lack those columns)
    sess_sub, sess_params = build_session_model_filter(filters)
    if sess_sub:
        w_prompt += f" AND up.session_id IN ({sess_sub})"
        p_prompt.extend(sess_params)
        w_session += f" AND s.session_id IN ({sess_sub})"
        p_session.extend(list(sess_params))

    # Peak hours heatmap
    st.subheader("Activity Heatmap (Hour x Day of Week)")
    df = query(f"""
        SELECT EXTRACT(DOW FROM up.timestamp) AS day_of_week,
               EXTRACT(HOUR FROM up.timestamp) AS hour,
               COUNT(*) AS prompt_count
        FROM user_prompts up JOIN employees e ON up.user_email = e.email
        WHERE {w_prompt}
        GROUP BY day_of_week, hour ORDER BY day_of_week, hour
    """, params=p_prompt)
    if not df.empty:
        day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        df["day_name"] = df["day_of_week"].astype(int).map(lambda d: day_names[d])
        pivot = df.pivot_table(index="day_name", columns="hour", values="prompt_count", fill_value=0)
        pivot = pivot.reindex(index=[d for d in day_names if d in pivot.index],
                              columns=range(24), fill_value=0)
        fig = px.imshow(pivot.values, x=[f"{h}:00" for h in range(24)], y=pivot.index.tolist(),
                        color_continuous_scale="YlOrRd", labels={"color": "Prompts"}, aspect="auto")
        fig.update_layout(height=300)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption(NO_DATA)

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Avg Session Depth by Practice")
        df = query(f"""
            SELECT e.practice,
                AVG(s.num_turns) AS avg_turns,
                AVG(s.num_api_calls) AS avg_api_calls,
                AVG(s.num_tool_uses) AS avg_tool_uses,
                COUNT(*) AS num_sessions
            FROM sessions s JOIN employees e ON s.user_email = e.email
            WHERE {w_session}
            GROUP BY e.practice
        """, params=p_session)
        if not df.empty:
            fig = go.Figure()
            fig.add_trace(go.Bar(name="Avg Turns", x=df["practice"], y=df["avg_turns"]))
            fig.add_trace(go.Bar(name="Avg API Calls", x=df["practice"], y=df["avg_api_calls"]))
            fig.add_trace(go.Bar(name="Avg Tool Uses", x=df["practice"], y=df["avg_tool_uses"]))
            fig.update_layout(barmode="group", height=400, xaxis_tickangle=-20)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption(NO_DATA)

    with col2:
        st.subheader("Cost Efficiency by Practice")
        df = query(f"""
            SELECT e.practice,
                SUM(s.total_cost) / NULLIF(SUM(s.num_turns), 0) AS cost_per_prompt,
                AVG(s.total_cost) AS avg_cost_per_session
            FROM sessions s JOIN employees e ON s.user_email = e.email
            WHERE {w_session}
            GROUP BY e.practice ORDER BY cost_per_prompt DESC
        """, params=p_session)
        if not df.empty:
            fig = px.bar(df, x="practice", y="cost_per_prompt", color="practice",
                         labels={"cost_per_prompt": "Cost per Prompt (USD)", "practice": "Practice"})
            fig.update_layout(showlegend=False, height=400, xaxis_tickangle=-20)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption(NO_DATA)

    st.markdown("---")

    st.subheader("IDE / Terminal Adoption by Practice")
    df = query(f"""
        SELECT e.practice, a.terminal_type, COUNT(DISTINCT a.session_id) AS session_count
        FROM api_requests a JOIN employees e ON a.user_email = e.email
        WHERE {w_api}
        GROUP BY e.practice, a.terminal_type ORDER BY e.practice, session_count DESC
    """, params=p_api)
    if not df.empty:
        fig = px.bar(df, x="practice", y="session_count", color="terminal_type", barmode="stack",
                     labels={"session_count": "Sessions", "terminal_type": "IDE / Terminal", "practice": "Practice"})
        fig.update_layout(height=400, xaxis_tickangle=-20)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption(NO_DATA)
