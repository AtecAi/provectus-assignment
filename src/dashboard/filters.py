"""Global sidebar filters for the dashboard."""

import streamlit as st
from src.analytics.queries import query


def render_filters():
    """Render sidebar filters and return a dict of selected values."""
    st.sidebar.markdown("### Filters")

    # Date range
    dates = query("SELECT MIN(start_time)::DATE AS min_d, MAX(end_time)::DATE AS max_d FROM sessions")
    min_date = dates["min_d"].iloc[0]
    max_date = dates["max_d"].iloc[0]
    date_range = st.sidebar.date_input("Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date)

    # Practice
    practices = query("SELECT DISTINCT practice FROM employees ORDER BY practice")["practice"].tolist()
    if st.sidebar.checkbox("All practices", value=True, key="all_practices"):
        selected_practices = practices
        if "sel_practices" in st.session_state:
            st.session_state["sel_practices"] = practices
    else:
        selected_practices = st.sidebar.multiselect("Practice", practices, default=practices, key="sel_practices")

    # Level
    levels = query("SELECT DISTINCT level FROM employees ORDER BY level")["level"].tolist()
    if st.sidebar.checkbox("All levels", value=True, key="all_levels"):
        selected_levels = levels
        if "sel_levels" in st.session_state:
            st.session_state["sel_levels"] = levels
    else:
        selected_levels = st.sidebar.multiselect("Level", levels, default=levels, key="sel_levels")

    # Location
    locations = query("SELECT DISTINCT location FROM employees ORDER BY location")["location"].tolist()
    if st.sidebar.checkbox("All locations", value=True, key="all_locations"):
        selected_locations = locations
        if "sel_locations" in st.session_state:
            st.session_state["sel_locations"] = locations
    else:
        selected_locations = st.sidebar.multiselect("Location", locations, default=locations, key="sel_locations")

    # Model
    models = query("SELECT DISTINCT model FROM api_requests WHERE model IS NOT NULL ORDER BY model")["model"].tolist()
    if st.sidebar.checkbox("All models", value=True, key="all_models"):
        selected_models = models
        if "sel_models" in st.session_state:
            st.session_state["sel_models"] = models
    else:
        selected_models = st.sidebar.multiselect("Model", models, default=models, key="sel_models")

    # IDE / Terminal
    terminals = query("SELECT DISTINCT terminal_type FROM api_requests WHERE terminal_type IS NOT NULL ORDER BY terminal_type")["terminal_type"].tolist()
    if st.sidebar.checkbox("All terminals", value=True, key="all_terminals"):
        selected_terminals = terminals
        if "sel_terminals" in st.session_state:
            st.session_state["sel_terminals"] = terminals
    else:
        selected_terminals = st.sidebar.multiselect("IDE / Terminal", terminals, default=terminals, key="sel_terminals")

    return {
        "date_start": date_range[0],
        "date_end": date_range[1] if len(date_range) == 2 else date_range[0],
        "practices": selected_practices,
        "levels": selected_levels,
        "locations": selected_locations,
        "models": selected_models,
        "terminals": selected_terminals,
    }



def build_session_model_filter(filters):
    """Return (subquery, params) to filter session_ids by model/terminal via api_requests.

    Use this for tables that lack model/terminal columns (tool_decisions,
    tool_results, user_prompts, sessions) so that sidebar model/terminal
    filters are applied globally.
    """
    conditions = []
    params = []
    models = filters.get("models")
    if models:
        placeholders = ", ".join("?" for _ in models)
        conditions.append(f"model IN ({placeholders})")
        params.extend(models)
    elif models is not None:
        return "SELECT NULL WHERE FALSE", []
    terminals = filters.get("terminals")
    if terminals:
        placeholders = ", ".join("?" for _ in terminals)
        conditions.append(f"terminal_type IN ({placeholders})")
        params.extend(terminals)
    elif terminals is not None:
        return "SELECT NULL WHERE FALSE", []
    if conditions:
        return f"SELECT DISTINCT session_id FROM api_requests WHERE {' AND '.join(conditions)}", params
    return None, []


def build_where_clause(filters, timestamp_col="a.timestamp", employee_alias="e",
                       model_col=None, terminal_col=None):
    """Build parameterized SQL WHERE clause. Returns (clause, params)."""
    conditions = []
    params = []

    conditions.append(f"{timestamp_col} >= ?")
    params.append(str(filters['date_start'])[:10])
    conditions.append(f"{timestamp_col} <= ?")
    params.append(f"{str(filters['date_end'])[:10]} 23:59:59")

    for values, col in [
        (filters["practices"], f"{employee_alias}.practice"),
        (filters["levels"], f"{employee_alias}.level"),
        (filters["locations"], f"{employee_alias}.location"),
    ]:
        if values:
            placeholders = ", ".join("?" for _ in values)
            conditions.append(f"{col} IN ({placeholders})")
            params.extend(values)
        else:
            conditions.append("FALSE")

    if model_col:
        models = filters.get("models")
        if models:
            placeholders = ", ".join("?" for _ in models)
            conditions.append(f"{model_col} IN ({placeholders})")
            params.extend(models)
        elif models is not None:
            conditions.append("FALSE")

    if terminal_col:
        terminals = filters.get("terminals")
        if terminals:
            placeholders = ", ".join("?" for _ in terminals)
            conditions.append(f"{terminal_col} IN ({placeholders})")
            params.extend(terminals)
        elif terminals is not None:
            conditions.append("FALSE")

    clause = " AND ".join(conditions) if conditions else "1=1"
    return clause, params
