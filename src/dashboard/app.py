"""Claude Code Usage Analytics Dashboard."""

import streamlit as st

st.set_page_config(
    page_title="Claude Code Analytics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

from src.dashboard.views import overview, cost_tokens, tool_usage, user_behavior, operational_health, advanced_analytics
from src.dashboard.filters import render_filters

PAGES = {
    "Overview": overview,
    "Cost & Tokens": cost_tokens,
    "Tool Usage": tool_usage,
    "User Behavior": user_behavior,
    "Operational Health": operational_health,
    "Advanced Analytics": advanced_analytics,
}

st.sidebar.title("Claude Code Analytics")
filters = render_filters()


page_names = list(PAGES.keys())
tabs = st.tabs(page_names)
for tab, name in zip(tabs, page_names):
    with tab:
        PAGES[name].render(filters)
