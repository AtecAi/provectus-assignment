"""Global sidebar filters for the dashboard."""

import streamlit as st
from src.analytics.queries import query


def _reset_filter_state(defaults):
    """Restore all filter widgets to their default values."""
    for key, value in defaults.items():
        st.session_state[key] = value


def _render_multiselect_filter(label, options, all_label, all_key, select_key):
    """Render a stable checkbox + multiselect pair.

    Keeping the multiselect mounted avoids Streamlit state glitches when a user
    clears all selections and then wants to add options back.
    """
    if all_key not in st.session_state:
        st.session_state[all_key] = True

    current = st.session_state.get(select_key, options)
    st.session_state[select_key] = [value for value in current if value in options]

    all_selected = st.sidebar.checkbox(all_label, key=all_key)
    if all_selected:
        st.session_state[select_key] = options

    st.sidebar.multiselect(
        label,
        options,
        key=select_key,
        disabled=all_selected,
    )

    return options if all_selected else st.session_state[select_key]


def render_filters():
    """Render sidebar filters and return a dict of selected values."""
    st.sidebar.markdown("### Filters")

    # Load filter option lists first so reset can happen before widgets render.
    dates = query("SELECT MIN(start_time)::DATE AS min_d, MAX(end_time)::DATE AS max_d FROM sessions")
    min_date = dates["min_d"].iloc[0]
    max_date = dates["max_d"].iloc[0]
    practices = query("SELECT DISTINCT practice FROM employees ORDER BY practice")["practice"].tolist()
    levels = query("SELECT DISTINCT level FROM employees ORDER BY level")["level"].tolist()
    locations = query("SELECT DISTINCT location FROM employees ORDER BY location")["location"].tolist()
    models = query("SELECT DISTINCT model FROM api_requests WHERE model IS NOT NULL ORDER BY model")["model"].tolist()
    terminals = query("SELECT DISTINCT terminal_type FROM api_requests WHERE terminal_type IS NOT NULL ORDER BY terminal_type")["terminal_type"].tolist()

    defaults = {
        "date_range": (min_date, max_date),
        "all_practices": True,
        "sel_practices": practices,
        "all_levels": True,
        "sel_levels": levels,
        "all_locations": True,
        "sel_locations": locations,
        "all_models": True,
        "sel_models": models,
        "all_terminals": True,
        "sel_terminals": terminals,
    }

    if st.sidebar.button("Reset filters", use_container_width=True):
        _reset_filter_state(defaults)
        st.rerun()

    if "date_range" not in st.session_state:
        st.session_state["date_range"] = (min_date, max_date)

    date_range = st.sidebar.date_input(
        "Date range",
        min_value=min_date,
        max_value=max_date,
        key="date_range",
    )

    selected_practices = _render_multiselect_filter(
        "Practice", practices, "All practices", "all_practices", "sel_practices"
    )
    selected_levels = _render_multiselect_filter(
        "Level", levels, "All levels", "all_levels", "sel_levels"
    )
    selected_locations = _render_multiselect_filter(
        "Location", locations, "All locations", "all_locations", "sel_locations"
    )
    selected_models = _render_multiselect_filter(
        "Model", models, "All models", "all_models", "sel_models"
    )
    selected_terminals = _render_multiselect_filter(
        "IDE / Terminal", terminals, "All terminals", "all_terminals", "sel_terminals"
    )

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
