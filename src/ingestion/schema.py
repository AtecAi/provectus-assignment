"""DuckDB schema definitions."""

TABLES = {
    "api_requests": """
        CREATE TABLE IF NOT EXISTS api_requests (
            event_id              TEXT PRIMARY KEY,
            timestamp             TIMESTAMP NOT NULL,
            session_id            TEXT NOT NULL,
            user_email            TEXT NOT NULL,
            terminal_type         TEXT,
            org_id                TEXT,
            scope_version         TEXT,
            host_arch             TEXT,
            os_type               TEXT,
            model                 TEXT NOT NULL,
            input_tokens          INTEGER,
            output_tokens         INTEGER,
            cache_read_tokens     INTEGER,
            cache_creation_tokens INTEGER,
            cost_usd              DOUBLE,
            duration_ms           INTEGER
        )
    """,
    "tool_decisions": """
        CREATE TABLE IF NOT EXISTS tool_decisions (
            event_id        TEXT PRIMARY KEY,
            timestamp       TIMESTAMP NOT NULL,
            session_id      TEXT NOT NULL,
            user_email      TEXT NOT NULL,
            terminal_type   TEXT,
            org_id          TEXT,
            scope_version   TEXT,
            host_arch       TEXT,
            os_type         TEXT,
            tool_name       TEXT NOT NULL,
            decision        TEXT NOT NULL,
            source          TEXT NOT NULL
        )
    """,
    "tool_results": """
        CREATE TABLE IF NOT EXISTS tool_results (
            event_id            TEXT PRIMARY KEY,
            timestamp           TIMESTAMP NOT NULL,
            session_id          TEXT NOT NULL,
            user_email          TEXT NOT NULL,
            terminal_type       TEXT,
            org_id              TEXT,
            scope_version       TEXT,
            host_arch           TEXT,
            os_type             TEXT,
            tool_name           TEXT NOT NULL,
            success             BOOLEAN,
            duration_ms         INTEGER,
            decision_source     TEXT,
            decision_type       TEXT,
            result_size_bytes   INTEGER
        )
    """,
    "user_prompts": """
        CREATE TABLE IF NOT EXISTS user_prompts (
            event_id        TEXT PRIMARY KEY,
            timestamp       TIMESTAMP NOT NULL,
            session_id      TEXT NOT NULL,
            user_email      TEXT NOT NULL,
            terminal_type   TEXT,
            org_id          TEXT,
            scope_version   TEXT,
            host_arch       TEXT,
            os_type         TEXT,
            prompt_length   INTEGER
        )
    """,
    "api_errors": """
        CREATE TABLE IF NOT EXISTS api_errors (
            event_id        TEXT PRIMARY KEY,
            timestamp       TIMESTAMP NOT NULL,
            session_id      TEXT NOT NULL,
            user_email      TEXT NOT NULL,
            terminal_type   TEXT,
            org_id          TEXT,
            scope_version   TEXT,
            host_arch       TEXT,
            os_type         TEXT,
            model           TEXT,
            error           TEXT,
            status_code     TEXT,
            attempt         INTEGER,
            duration_ms     INTEGER
        )
    """,
    "employees": """
        CREATE TABLE IF NOT EXISTS employees (
            email       TEXT PRIMARY KEY,
            full_name   TEXT,
            practice    TEXT,
            level       TEXT,
            location    TEXT
        )
    """,
    "sessions": """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id          TEXT PRIMARY KEY,
            user_email          TEXT NOT NULL,
            start_time          TIMESTAMP,
            end_time            TIMESTAMP,
            duration_sec        INTEGER,
            num_turns           INTEGER,
            num_api_calls       INTEGER,
            num_tool_uses       INTEGER,
            total_cost          DOUBLE,
            total_input_tokens  INTEGER,
            total_output_tokens INTEGER,
            error_count         INTEGER
        )
    """,
    "data_quality": """
        CREATE TABLE IF NOT EXISTS data_quality (
            table_name          TEXT NOT NULL,
            field_name          TEXT NOT NULL,
            total_rows          INTEGER NOT NULL,
            null_count          INTEGER NOT NULL,
            parse_failure_count INTEGER NOT NULL,
            is_optional         BOOLEAN NOT NULL DEFAULT FALSE,
            PRIMARY KEY (table_name, field_name)
        )
    """,
}

SESSIONS_AGGREGATION = """
    INSERT INTO sessions
    SELECT
        s.session_id,
        s.user_email,
        s.start_time,
        s.end_time,
        CAST(EXTRACT(EPOCH FROM (s.end_time - s.start_time)) AS INTEGER) AS duration_sec,
        COALESCE(p.num_turns, 0) AS num_turns,
        COALESCE(a.num_api_calls, 0) AS num_api_calls,
        COALESCE(t.num_tool_uses, 0) AS num_tool_uses,
        CASE WHEN a.num_api_calls IS NULL THEN 0.0 ELSE a.total_cost END AS total_cost,
        CASE WHEN a.num_api_calls IS NULL THEN 0 ELSE a.total_input_tokens END AS total_input_tokens,
        CASE WHEN a.num_api_calls IS NULL THEN 0 ELSE a.total_output_tokens END AS total_output_tokens,
        COALESCE(e.error_count, 0) AS error_count
    FROM (
        SELECT
            session_id,
            MIN(user_email) AS user_email,
            MIN(timestamp) AS start_time,
            MAX(timestamp) AS end_time
        FROM (
            SELECT session_id, user_email, timestamp FROM api_requests
            UNION ALL
            SELECT session_id, user_email, timestamp FROM tool_decisions
            UNION ALL
            SELECT session_id, user_email, timestamp FROM tool_results
            UNION ALL
            SELECT session_id, user_email, timestamp FROM user_prompts
            UNION ALL
            SELECT session_id, user_email, timestamp FROM api_errors
        )
        GROUP BY session_id
    ) s
    LEFT JOIN (
        SELECT session_id, COUNT(*) AS num_turns
        FROM user_prompts
        GROUP BY session_id
    ) p ON s.session_id = p.session_id
    LEFT JOIN (
        SELECT
            session_id,
            COUNT(*) AS num_api_calls,
            SUM(cost_usd) AS total_cost,
            SUM(input_tokens) AS total_input_tokens,
            SUM(output_tokens) AS total_output_tokens
        FROM api_requests
        GROUP BY session_id
    ) a ON s.session_id = a.session_id
    LEFT JOIN (
        SELECT session_id, COUNT(*) AS num_tool_uses
        FROM tool_results
        GROUP BY session_id
    ) t ON s.session_id = t.session_id
    LEFT JOIN (
        SELECT session_id, COUNT(*) AS error_count
        FROM api_errors
        GROUP BY session_id
    ) e ON s.session_id = e.session_id
"""
