"""FastAPI endpoints for programmatic access to analytics."""

from datetime import date
from fastapi import FastAPI, Depends, Query
from typing import Optional, List

from src.analytics.queries import query, DB_PATH

app = FastAPI(
    title="Claude Code Analytics API",
    description="Programmatic access to Claude Code telemetry analytics",
    version="1.0.0",
)


def df_to_response(df):
    """Convert DataFrame to JSON-serializable list of dicts."""
    return df.to_dict(orient="records")


class FilterParams:
    """Common query parameter filters injected via Depends."""

    def __init__(
        self,
        date_start: Optional[date] = None,
        date_end: Optional[date] = None,
        practice: Optional[List[str]] = Query(None),
        level: Optional[List[str]] = Query(None),
        location: Optional[List[str]] = Query(None),
        model: Optional[List[str]] = Query(None),
        terminal_type: Optional[List[str]] = Query(None),
    ):
        self.date_start = date_start
        self.date_end = date_end
        self.practice = practice
        self.level = level
        self.location = location
        self.model = model
        self.terminal_type = terminal_type

    def where(self, timestamp_col="a.timestamp", employee_alias="e",
              model_col=None, terminal_col=None):
        """Build parameterized SQL WHERE clause. Returns (clause, params)."""
        conditions = []
        params = []
        if self.date_start:
            conditions.append(f"{timestamp_col} >= ?")
            params.append(str(self.date_start)[:10])
        if self.date_end:
            conditions.append(f"{timestamp_col} <= ?")
            params.append(f"{str(self.date_end)[:10]} 23:59:59")
        for values, col in [
            (self.practice, f"{employee_alias}.practice"),
            (self.level, f"{employee_alias}.level"),
            (self.location, f"{employee_alias}.location"),
        ]:
            if values is not None:
                if values:
                    placeholders = ", ".join("?" for _ in values)
                    conditions.append(f"{col} IN ({placeholders})")
                    params.extend(values)
                else:
                    conditions.append("FALSE")
        if model_col and self.model is not None:
            if self.model:
                placeholders = ", ".join("?" for _ in self.model)
                conditions.append(f"{model_col} IN ({placeholders})")
                params.extend(self.model)
            else:
                conditions.append("FALSE")
        if terminal_col and self.terminal_type is not None:
            if self.terminal_type:
                placeholders = ", ".join("?" for _ in self.terminal_type)
                conditions.append(f"{terminal_col} IN ({placeholders})")
                params.extend(self.terminal_type)
            else:
                conditions.append("FALSE")
        clause = " AND ".join(conditions) if conditions else "1=1"
        return clause, params

    def session_model_filter(self, session_alias):
        """Return (clause_fragment, params) to filter by model/terminal via session subquery.

        For tables that lack model/terminal columns (tool_decisions,
        tool_results, user_prompts, sessions, api_errors).
        """
        conditions = []
        params = []
        if self.model is not None:
            if self.model:
                placeholders = ", ".join("?" for _ in self.model)
                conditions.append(f"model IN ({placeholders})")
                params.extend(self.model)
            else:
                return f" AND {session_alias}.session_id IN (SELECT NULL WHERE FALSE)", []
        if self.terminal_type is not None:
            if self.terminal_type:
                placeholders = ", ".join("?" for _ in self.terminal_type)
                conditions.append(f"terminal_type IN ({placeholders})")
                params.extend(self.terminal_type)
            else:
                return f" AND {session_alias}.session_id IN (SELECT NULL WHERE FALSE)", []
        if conditions:
            sub = f"SELECT DISTINCT session_id FROM api_requests WHERE {' AND '.join(conditions)}"
            return f" AND {session_alias}.session_id IN ({sub})", params
        return "", []


# --- Overview ---

@app.get("/api/v1/overview")
def get_overview(f: FilterParams = Depends()):
    w, p = f.where(timestamp_col="s.start_time")
    sf, sp = f.session_model_filter("s")
    return df_to_response(query(f"""
        SELECT
            COALESCE(SUM(s.total_cost), 0) AS total_cost,
            COUNT(*) AS total_sessions,
            COUNT(DISTINCT s.user_email) AS active_users,
            COALESCE(SUM(s.error_count), 0) AS total_errors,
            COALESCE(SUM(s.num_api_calls), 0) AS total_api_calls
        FROM sessions s JOIN employees e ON s.user_email = e.email
        WHERE {w}{sf}
    """, params=p + sp))


@app.get("/api/v1/activity/daily")
def get_daily_activity(f: FilterParams = Depends()):
    w, p = f.where(timestamp_col="up.timestamp")
    sf, sp = f.session_model_filter("up")
    return df_to_response(query(f"""
        SELECT CAST(up.timestamp AS DATE) AS date,
            COUNT(*) AS prompt_count,
            COUNT(DISTINCT up.session_id) AS session_count,
            COUNT(DISTINCT up.user_email) AS active_users
        FROM user_prompts up JOIN employees e ON up.user_email = e.email
        WHERE {w}{sf} GROUP BY date ORDER BY date
    """, params=p + sp))


# --- Cost & Tokens ---

@app.get("/api/v1/cost/daily")
def get_daily_cost(f: FilterParams = Depends()):
    w, p = f.where(model_col="a.model", terminal_col="a.terminal_type")
    return df_to_response(query(f"""
        SELECT CAST(a.timestamp AS DATE) AS date, SUM(a.cost_usd) AS daily_cost
        FROM api_requests a JOIN employees e ON a.user_email = e.email
        WHERE {w} GROUP BY date ORDER BY date
    """, params=p))


@app.get("/api/v1/cost/by-practice")
def get_cost_by_practice(f: FilterParams = Depends()):
    w, p = f.where(model_col="a.model", terminal_col="a.terminal_type")
    return df_to_response(query(f"""
        SELECT e.practice, SUM(a.cost_usd) AS total_cost, COUNT(*) AS num_requests
        FROM api_requests a JOIN employees e ON a.user_email = e.email
        WHERE {w} GROUP BY e.practice ORDER BY total_cost DESC
    """, params=p))


@app.get("/api/v1/cost/by-model")
def get_cost_by_model(f: FilterParams = Depends()):
    w, p = f.where(model_col="a.model", terminal_col="a.terminal_type")
    return df_to_response(query(f"""
        SELECT a.model, SUM(a.cost_usd) AS total_cost
        FROM api_requests a JOIN employees e ON a.user_email = e.email
        WHERE {w} GROUP BY a.model ORDER BY total_cost DESC
    """, params=p))


@app.get("/api/v1/cost/by-practice-and-level")
def get_cost_by_practice_and_level(f: FilterParams = Depends()):
    w, p = f.where(model_col="a.model", terminal_col="a.terminal_type")
    return df_to_response(query(f"""
        SELECT e.practice, e.level, SUM(a.cost_usd) AS total_cost
        FROM api_requests a JOIN employees e ON a.user_email = e.email
        WHERE {w} GROUP BY e.practice, e.level ORDER BY e.practice, e.level
    """, params=p))


@app.get("/api/v1/tokens/by-practice")
def get_tokens_by_practice(f: FilterParams = Depends()):
    w, p = f.where(model_col="a.model", terminal_col="a.terminal_type")
    return df_to_response(query(f"""
        SELECT e.practice,
            SUM(a.input_tokens) AS total_input_tokens,
            SUM(a.output_tokens) AS total_output_tokens,
            SUM(a.cache_read_tokens) AS total_cache_read_tokens,
            SUM(a.cache_creation_tokens) AS total_cache_creation_tokens
        FROM api_requests a JOIN employees e ON a.user_email = e.email
        WHERE {w} GROUP BY e.practice ORDER BY total_input_tokens DESC
    """, params=p))


@app.get("/api/v1/tokens/by-level")
def get_tokens_by_level(f: FilterParams = Depends()):
    w, p = f.where(model_col="a.model", terminal_col="a.terminal_type")
    return df_to_response(query(f"""
        SELECT e.level,
            SUM(a.input_tokens) AS total_input_tokens,
            SUM(a.output_tokens) AS total_output_tokens
        FROM api_requests a JOIN employees e ON a.user_email = e.email
        WHERE {w} GROUP BY e.level ORDER BY e.level
    """, params=p))


# --- Tool Usage ---

@app.get("/api/v1/tools/usage")
def get_tool_usage(f: FilterParams = Depends()):
    w, p = f.where(timestamp_col="td.timestamp")
    sf, sp = f.session_model_filter("td")
    return df_to_response(query(f"""
        SELECT td.tool_name, COUNT(*) AS usage_count,
            SUM(CASE WHEN td.decision = 'accept' THEN 1 ELSE 0 END) AS accepted,
            SUM(CASE WHEN td.decision = 'reject' THEN 1 ELSE 0 END) AS rejected
        FROM tool_decisions td JOIN employees e ON td.user_email = e.email
        WHERE {w}{sf} GROUP BY td.tool_name ORDER BY usage_count DESC
    """, params=p + sp))


@app.get("/api/v1/tools/success-rates")
def get_tool_success_rates(f: FilterParams = Depends()):
    w, p = f.where(timestamp_col="tr.timestamp")
    sf, sp = f.session_model_filter("tr")
    return df_to_response(query(f"""
        SELECT tr.tool_name, COUNT(*) AS total_executions,
            COUNT(tr.success) AS known_outcomes,
            SUM(CASE WHEN tr.success THEN 1 ELSE 0 END) AS successes,
            ROUND(SUM(CASE WHEN tr.success THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(tr.success), 0), 2) AS success_rate,
            AVG(tr.duration_ms) AS avg_duration_ms
        FROM tool_results tr JOIN employees e ON tr.user_email = e.email
        WHERE {w}{sf} GROUP BY tr.tool_name ORDER BY success_rate ASC
    """, params=p + sp))


@app.get("/api/v1/tools/rejection-rate")
def get_tool_rejection_rate(f: FilterParams = Depends()):
    w, p = f.where(timestamp_col="td.timestamp")
    sf, sp = f.session_model_filter("td")
    return df_to_response(query(f"""
        SELECT td.tool_name, e.level,
            SUM(CASE WHEN td.decision = 'reject' THEN 1 ELSE 0 END) AS rejected,
            COUNT(*) AS total,
            ROUND(SUM(CASE WHEN td.decision = 'reject' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS reject_pct
        FROM tool_decisions td JOIN employees e ON td.user_email = e.email
        WHERE {w}{sf} GROUP BY td.tool_name, e.level ORDER BY td.tool_name, e.level
    """, params=p + sp))


# --- User Behavior ---

@app.get("/api/v1/usage/peak-hours")
def get_peak_hours(f: FilterParams = Depends()):
    w, p = f.where(timestamp_col="up.timestamp")
    sf, sp = f.session_model_filter("up")
    return df_to_response(query(f"""
        SELECT EXTRACT(HOUR FROM up.timestamp) AS hour, COUNT(*) AS prompt_count
        FROM user_prompts up JOIN employees e ON up.user_email = e.email
        WHERE {w}{sf} GROUP BY hour ORDER BY hour
    """, params=p + sp))


@app.get("/api/v1/usage/peak-days")
def get_peak_days(f: FilterParams = Depends()):
    w, p = f.where(timestamp_col="up.timestamp")
    sf, sp = f.session_model_filter("up")
    return df_to_response(query(f"""
        SELECT EXTRACT(DOW FROM up.timestamp) AS day_of_week, COUNT(*) AS prompt_count
        FROM user_prompts up JOIN employees e ON up.user_email = e.email
        WHERE {w}{sf} GROUP BY day_of_week ORDER BY day_of_week
    """, params=p + sp))


@app.get("/api/v1/sessions/depth")
def get_session_depth(f: FilterParams = Depends()):
    w, p = f.where(timestamp_col="s.start_time")
    sf, sp = f.session_model_filter("s")
    return df_to_response(query(f"""
        SELECT e.practice,
            AVG(s.num_turns) AS avg_turns,
            AVG(s.num_api_calls) AS avg_api_calls,
            AVG(s.num_tool_uses) AS avg_tool_uses,
            COUNT(*) AS num_sessions
        FROM sessions s JOIN employees e ON s.user_email = e.email
        WHERE {w}{sf} GROUP BY e.practice
    """, params=p + sp))


@app.get("/api/v1/cost/efficiency")
def get_cost_efficiency(f: FilterParams = Depends()):
    w, p = f.where(timestamp_col="s.start_time")
    sf, sp = f.session_model_filter("s")
    return df_to_response(query(f"""
        SELECT e.practice,
            SUM(s.total_cost) / NULLIF(SUM(s.num_turns), 0) AS cost_per_prompt,
            AVG(s.total_cost) AS avg_cost_per_session
        FROM sessions s JOIN employees e ON s.user_email = e.email
        WHERE {w}{sf} GROUP BY e.practice ORDER BY cost_per_prompt DESC
    """, params=p + sp))


@app.get("/api/v1/ide/adoption")
def get_ide_adoption(f: FilterParams = Depends()):
    w, p = f.where(terminal_col="a.terminal_type")
    return df_to_response(query(f"""
        SELECT e.practice, a.terminal_type, COUNT(DISTINCT a.session_id) AS session_count
        FROM api_requests a JOIN employees e ON a.user_email = e.email
        WHERE {w} GROUP BY e.practice, a.terminal_type ORDER BY e.practice, session_count DESC
    """, params=p))


# --- Operational Health ---

@app.get("/api/v1/errors/daily")
def get_errors_daily(f: FilterParams = Depends()):
    w, p = f.where(timestamp_col="ae.timestamp", model_col="ae.model", terminal_col="ae.terminal_type")
    return df_to_response(query(f"""
        SELECT CAST(ae.timestamp AS DATE) AS date, ae.status_code, COUNT(*) AS error_count
        FROM api_errors ae JOIN employees e ON ae.user_email = e.email
        WHERE {w} GROUP BY date, ae.status_code ORDER BY date
    """, params=p))


@app.get("/api/v1/models/latency")
def get_model_latency(f: FilterParams = Depends()):
    w, p = f.where(model_col="a.model", terminal_col="a.terminal_type")
    return df_to_response(query(f"""
        SELECT a.model,
            AVG(a.duration_ms) AS avg_duration_ms,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY a.duration_ms) AS p50_ms,
            PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY a.duration_ms) AS p90_ms,
            PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY a.duration_ms) AS p99_ms,
            COUNT(*) AS num_requests
        FROM api_requests a JOIN employees e ON a.user_email = e.email
        WHERE {w} GROUP BY a.model ORDER BY avg_duration_ms DESC
    """, params=p))


@app.get("/api/v1/models/preference")
def get_model_preference(f: FilterParams = Depends()):
    w, p = f.where(model_col="a.model", terminal_col="a.terminal_type")
    return df_to_response(query(f"""
        SELECT e.practice, a.model, COUNT(*) AS request_count
        FROM api_requests a JOIN employees e ON a.user_email = e.email
        WHERE {w} GROUP BY e.practice, a.model ORDER BY e.practice, request_count DESC
    """, params=p))


@app.get("/api/v1/versions/distribution")
def get_version_distribution(f: FilterParams = Depends()):
    w, p = f.where(model_col="a.model", terminal_col="a.terminal_type")
    return df_to_response(query(f"""
        SELECT a.scope_version AS version,
            COUNT(DISTINCT a.user_email) AS user_count,
            COUNT(*) AS event_count
        FROM api_requests a JOIN employees e ON a.user_email = e.email
        WHERE {w} GROUP BY a.scope_version ORDER BY user_count DESC, version LIMIT 15
    """, params=p))


# --- Data Quality ---

@app.get("/api/v1/data-quality")
def get_data_quality():
    return df_to_response(query(
        "SELECT table_name, field_name, total_rows, null_count, parse_failure_count, is_optional FROM data_quality ORDER BY table_name, field_name"
    ))


# --- Sessions ---

@app.get("/api/v1/sessions/{session_id}")
def get_session(session_id: str):
    from src.analytics.queries import get_connection
    con = get_connection()
    try:
        df = con.execute("SELECT * FROM sessions WHERE session_id = ?", [session_id]).df()
    finally:
        con.close()
    if df.empty:
        return {"error": "Session not found"}
    return df_to_response(df)[0]
