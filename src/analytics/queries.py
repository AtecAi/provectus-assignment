"""Analytics query functions. Each returns a pandas DataFrame."""

import duckdb
import pandas as pd

DB_PATH = "output/analytics.duckdb"


def get_connection(db_path=DB_PATH):
    return duckdb.connect(db_path, read_only=True)


def query(sql, db_path=DB_PATH, *, params=None):
    con = get_connection(db_path)
    try:
        if params:
            return con.execute(sql, params).df()
        return con.execute(sql).df()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Tier 1: Required analytics
# ---------------------------------------------------------------------------

def token_consumption_by_practice(db_path=DB_PATH):
    """A1: Token consumption by engineering practice."""
    return query("""
        SELECT
            e.practice,
            SUM(a.input_tokens) AS total_input_tokens,
            SUM(a.output_tokens) AS total_output_tokens,
            SUM(a.cache_read_tokens) AS total_cache_read_tokens,
            SUM(a.cache_creation_tokens) AS total_cache_creation_tokens,
            SUM(COALESCE(a.input_tokens, 0) + COALESCE(a.output_tokens, 0)) AS total_direct_tokens,
            COUNT(*) AS num_requests
        FROM api_requests a
        JOIN employees e ON a.user_email = e.email
        GROUP BY e.practice
        ORDER BY total_direct_tokens DESC
    """, db_path)


def token_consumption_by_level(db_path=DB_PATH):
    """A2: Token consumption by seniority level."""
    return query("""
        SELECT
            e.level,
            SUM(a.input_tokens) AS total_input_tokens,
            SUM(a.output_tokens) AS total_output_tokens,
            SUM(a.cache_read_tokens) AS total_cache_read_tokens,
            SUM(a.cache_creation_tokens) AS total_cache_creation_tokens,
            COUNT(*) AS num_requests
        FROM api_requests a
        JOIN employees e ON a.user_email = e.email
        GROUP BY e.level
        ORDER BY e.level
    """, db_path)


def cost_by_practice_and_level(db_path=DB_PATH):
    """A3: Cost breakdown by practice and level."""
    return query("""
        SELECT
            e.practice,
            e.level,
            SUM(a.cost_usd) AS total_cost,
            AVG(a.cost_usd) AS avg_cost_per_request,
            COUNT(*) AS num_requests
        FROM api_requests a
        JOIN employees e ON a.user_email = e.email
        GROUP BY e.practice, e.level
        ORDER BY e.practice, e.level
    """, db_path)


def peak_usage_by_hour(db_path=DB_PATH):
    """A4: User activity by hour of day (based on user_prompt events)."""
    return query("""
        SELECT
            EXTRACT(HOUR FROM timestamp) AS hour,
            COUNT(*) AS prompt_count,
            COUNT(DISTINCT session_id) AS session_count
        FROM user_prompts
        GROUP BY hour
        ORDER BY hour
    """, db_path)


def peak_usage_by_day_of_week(db_path=DB_PATH):
    """A4: User activity by day of week."""
    return query("""
        SELECT
            EXTRACT(DOW FROM timestamp) AS day_of_week,
            COUNT(*) AS prompt_count,
            COUNT(DISTINCT session_id) AS session_count
        FROM user_prompts
        GROUP BY day_of_week
        ORDER BY day_of_week
    """, db_path)


def peak_usage_heatmap(db_path=DB_PATH):
    """A4: Hour x Day-of-week heatmap data."""
    return query("""
        SELECT
            EXTRACT(DOW FROM timestamp) AS day_of_week,
            EXTRACT(HOUR FROM timestamp) AS hour,
            COUNT(*) AS prompt_count
        FROM user_prompts
        GROUP BY day_of_week, hour
        ORDER BY day_of_week, hour
    """, db_path)


def tool_usage_distribution(db_path=DB_PATH):
    """A5: Tool usage across all 17 tool types."""
    return query("""
        SELECT
            tool_name,
            COUNT(*) AS usage_count,
            SUM(CASE WHEN decision = 'accept' THEN 1 ELSE 0 END) AS accepted,
            SUM(CASE WHEN decision = 'reject' THEN 1 ELSE 0 END) AS rejected
        FROM tool_decisions
        GROUP BY tool_name
        ORDER BY usage_count DESC
    """, db_path)


# ---------------------------------------------------------------------------
# Tier 2: Natural insights
# ---------------------------------------------------------------------------

def model_preference_by_practice(db_path=DB_PATH):
    """B1: Which models each practice uses."""
    return query("""
        SELECT
            e.practice,
            a.model,
            COUNT(*) AS request_count,
            SUM(a.cost_usd) AS total_cost,
            AVG(a.duration_ms) AS avg_duration_ms
        FROM api_requests a
        JOIN employees e ON a.user_email = e.email
        GROUP BY e.practice, a.model
        ORDER BY e.practice, request_count DESC
    """, db_path)


def session_depth_analysis(db_path=DB_PATH):
    """B2: Session depth stats."""
    return query("""
        SELECT
            e.practice,
            e.level,
            AVG(s.num_turns) AS avg_turns,
            AVG(s.num_api_calls) AS avg_api_calls,
            AVG(s.num_tool_uses) AS avg_tool_uses,
            AVG(s.duration_sec) AS avg_duration_sec,
            COUNT(*) AS num_sessions
        FROM sessions s
        JOIN employees e ON s.user_email = e.email
        GROUP BY e.practice, e.level
        ORDER BY e.practice, e.level
    """, db_path)


def error_patterns_over_time(db_path=DB_PATH):
    """B3: Daily error counts by type."""
    return query("""
        SELECT
            CAST(timestamp AS DATE) AS date,
            status_code,
            error,
            COUNT(*) AS error_count
        FROM api_errors
        GROUP BY date, status_code, error
        ORDER BY date, error_count DESC
    """, db_path)


def tool_rejection_rate(db_path=DB_PATH):
    """B4: Accept/reject ratio by tool and seniority."""
    return query("""
        SELECT
            td.tool_name,
            e.level,
            SUM(CASE WHEN td.decision = 'accept' THEN 1 ELSE 0 END) AS accepted,
            SUM(CASE WHEN td.decision = 'reject' THEN 1 ELSE 0 END) AS rejected,
            COUNT(*) AS total,
            ROUND(SUM(CASE WHEN td.decision = 'reject' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS reject_pct
        FROM tool_decisions td
        JOIN employees e ON td.user_email = e.email
        GROUP BY td.tool_name, e.level
        ORDER BY td.tool_name, e.level
    """, db_path)


def cost_efficiency(db_path=DB_PATH):
    """B5: Cost per prompt and per session by practice."""
    return query("""
        SELECT
            e.practice,
            SUM(s.total_cost) / NULLIF(SUM(s.num_turns), 0) AS cost_per_prompt,
            AVG(s.total_cost) AS avg_cost_per_session,
            SUM(s.total_cost) AS total_cost,
            SUM(s.num_turns) AS total_prompts,
            COUNT(*) AS num_sessions
        FROM sessions s
        JOIN employees e ON s.user_email = e.email
        GROUP BY e.practice
        ORDER BY cost_per_prompt DESC
    """, db_path)


def ide_adoption(db_path=DB_PATH):
    """B6: IDE/terminal distribution by practice."""
    return query("""
        SELECT
            e.practice,
            a.terminal_type,
            COUNT(DISTINCT a.session_id) AS session_count
        FROM api_requests a
        JOIN employees e ON a.user_email = e.email
        GROUP BY e.practice, a.terminal_type
        ORDER BY e.practice, session_count DESC
    """, db_path)


def version_distribution(db_path=DB_PATH):
    """B7: Claude Code version spread across users and practices."""
    return query("""
        SELECT
            e.practice,
            a.scope_version AS version,
            COUNT(DISTINCT a.user_email) AS user_count,
            COUNT(*) AS event_count
        FROM api_requests a
        JOIN employees e ON a.user_email = e.email
        GROUP BY e.practice, a.scope_version
        ORDER BY e.practice, user_count DESC
    """, db_path)


def tool_success_rates(db_path=DB_PATH):
    """B8: Success rates by tool."""
    return query("""
        SELECT
            tool_name,
            COUNT(*) AS total_executions,
            COUNT(success) AS known_outcomes,
            SUM(CASE WHEN success THEN 1 ELSE 0 END) AS successes,
            ROUND(SUM(CASE WHEN success THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(success), 0), 2) AS success_rate,
            AVG(duration_ms) AS avg_duration_ms
        FROM tool_results
        GROUP BY tool_name
        ORDER BY success_rate ASC
    """, db_path)


# ---------------------------------------------------------------------------
# Overview / KPI queries
# ---------------------------------------------------------------------------

def overview_kpis(db_path=DB_PATH):
    """Top-level KPI metrics."""
    return query("""
        SELECT
            (SELECT COALESCE(SUM(total_cost), 0) FROM sessions) AS total_cost,
            (SELECT COUNT(*) FROM sessions) AS total_sessions,
            (SELECT COUNT(DISTINCT user_email) FROM sessions) AS active_users,
            (SELECT COUNT(*) FROM api_errors) AS total_errors,
            (SELECT COUNT(*) FROM api_requests) AS total_api_calls,
            (SELECT ROUND(COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM api_requests), 0), 2) FROM api_errors) AS error_rate_pct
    """, db_path)


def daily_activity(db_path=DB_PATH):
    """Daily activity timeline."""
    return query("""
        SELECT
            CAST(timestamp AS DATE) AS date,
            COUNT(*) AS prompt_count,
            COUNT(DISTINCT session_id) AS session_count,
            COUNT(DISTINCT user_email) AS active_users
        FROM user_prompts
        GROUP BY date
        ORDER BY date
    """, db_path)


def daily_cost(db_path=DB_PATH):
    """Daily cost trend."""
    return query("""
        SELECT
            CAST(timestamp AS DATE) AS date,
            SUM(cost_usd) AS daily_cost,
            COUNT(*) AS num_requests
        FROM api_requests
        GROUP BY date
        ORDER BY date
    """, db_path)


def cost_by_practice(db_path=DB_PATH):
    """Total cost by practice."""
    return query("""
        SELECT
            e.practice,
            SUM(a.cost_usd) AS total_cost,
            COUNT(*) AS num_requests,
            AVG(a.cost_usd) AS avg_cost
        FROM api_requests a
        JOIN employees e ON a.user_email = e.email
        GROUP BY e.practice
        ORDER BY total_cost DESC
    """, db_path)


def cost_by_model(db_path=DB_PATH):
    """Total cost by model."""
    return query("""
        SELECT
            model,
            SUM(cost_usd) AS total_cost,
            COUNT(*) AS num_requests,
            AVG(cost_usd) AS avg_cost,
            AVG(duration_ms) AS avg_duration_ms
        FROM api_requests
        GROUP BY model
        ORDER BY total_cost DESC
    """, db_path)


def latency_by_model(db_path=DB_PATH):
    """Latency distribution by model."""
    return query("""
        SELECT
            model,
            AVG(duration_ms) AS avg_duration_ms,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50_ms,
            PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY duration_ms) AS p90_ms,
            PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99_ms,
            COUNT(*) AS num_requests
        FROM api_requests
        GROUP BY model
        ORDER BY avg_duration_ms DESC
    """, db_path)
