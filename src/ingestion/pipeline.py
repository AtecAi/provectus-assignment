"""Ingestion pipeline: parse telemetry JSONL, validate, load into DuckDB."""

import csv
import json
import logging
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from .schema import SESSIONS_AGGREGATION, TABLES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = "output/analytics.duckdb"
TELEMETRY_PATH = "output/telemetry_logs.jsonl"
EMPLOYEES_PATH = "output/employees.csv"

# Event type -> table name mapping
EVENT_TABLE_MAP = {
    "claude_code.api_request": "api_requests",
    "claude_code.tool_decision": "tool_decisions",
    "claude_code.tool_result": "tool_results",
    "claude_code.user_prompt": "user_prompts",
    "claude_code.api_error": "api_errors",
}

REQUIRED_FIELDS = {"event.timestamp", "session.id", "user.email"}

# Per-field parse failure counter — reset at start of each run()
_parse_failures = defaultdict(int)


def safe_int(value, default=None, field_key=None):
    """Parse int. Returns None for missing/malformed (not 0)."""
    try:
        return int(value)
    except (ValueError, TypeError):
        if field_key and value is not None:
            _parse_failures[field_key] += 1
        return default


def safe_float(value, default=None, field_key=None):
    """Parse float. Returns None for missing/malformed/non-finite (not 0.0)."""
    try:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("non-finite")
        return result
    except (ValueError, TypeError):
        if field_key and value is not None:
            _parse_failures[field_key] += 1
        return default


def safe_bool(value, field_key=None):
    """Parse boolean. Returns None for missing/malformed (not False).

    Handles both string "true"/"false" (from raw telemetry attributes)
    and Python True/False (from json.loads on JSON booleans).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.lower()
        if low == "true":
            return True
        if low == "false":
            return False
    if field_key:
        _parse_failures[field_key] += 1
    return None


def parse_timestamp(ts_str):
    try:
        # fromisoformat is ~3x faster than strptime; Python 3.9 needs Z→+00:00
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None


def extract_common_fields(event):
    """Extract fields shared across all event types."""
    attrs = event.get("attributes", {})
    scope = event.get("scope", {})
    resource = event.get("resource", {})

    # Use attributes.user.email (real email), not resource.user.email (always empty)
    return {
        "timestamp": parse_timestamp(attrs.get("event.timestamp")),
        "session_id": attrs.get("session.id"),
        "user_email": attrs.get("user.email"),
        "terminal_type": attrs.get("terminal.type"),
        "org_id": attrs.get("organization.id"),
        "scope_version": scope.get("version"),
        "host_arch": resource.get("host.arch"),
        "os_type": resource.get("os.type"),
    }


def extract_api_request(event, common):
    attrs = event["attributes"]
    return {
        **common,
        "model": attrs.get("model", ""),
        "input_tokens": safe_int(attrs.get("input_tokens"), field_key=("api_requests", "input_tokens")),
        "output_tokens": safe_int(attrs.get("output_tokens"), field_key=("api_requests", "output_tokens")),
        "cache_read_tokens": safe_int(attrs.get("cache_read_tokens"), field_key=("api_requests", "cache_read_tokens")),
        "cache_creation_tokens": safe_int(attrs.get("cache_creation_tokens"), field_key=("api_requests", "cache_creation_tokens")),
        "cost_usd": safe_float(attrs.get("cost_usd"), field_key=("api_requests", "cost_usd")),
        "duration_ms": safe_int(attrs.get("duration_ms"), field_key=("api_requests", "duration_ms")),
    }


def extract_tool_decision(event, common):
    attrs = event["attributes"]
    return {
        **common,
        "tool_name": attrs.get("tool_name", ""),
        "decision": attrs.get("decision", ""),
        "source": attrs.get("source", ""),
    }


def extract_tool_result(event, common):
    attrs = event["attributes"]
    return {
        **common,
        "tool_name": attrs.get("tool_name", ""),
        "success": safe_bool(attrs.get("success"), field_key=("tool_results", "success")),
        "duration_ms": safe_int(attrs.get("duration_ms"), field_key=("tool_results", "duration_ms")),
        "decision_source": attrs.get("decision_source"),
        "decision_type": attrs.get("decision_type"),
        "result_size_bytes": safe_int(attrs.get("tool_result_size_bytes"), field_key=("tool_results", "result_size_bytes")),
    }


def extract_user_prompt(event, common):
    attrs = event["attributes"]
    return {
        **common,
        "prompt_length": safe_int(attrs.get("prompt_length"), field_key=("user_prompts", "prompt_length")),
    }


def extract_api_error(event, common):
    attrs = event["attributes"]
    return {
        **common,
        "model": attrs.get("model"),
        "error": attrs.get("error"),
        "status_code": attrs.get("status_code"),  # kept as TEXT, some are "undefined"
        "attempt": safe_int(attrs.get("attempt"), field_key=("api_errors", "attempt")),
        "duration_ms": safe_int(attrs.get("duration_ms"), field_key=("api_errors", "duration_ms")),
    }


EXTRACTORS = {
    "claude_code.api_request": extract_api_request,
    "claude_code.tool_decision": extract_tool_decision,
    "claude_code.tool_result": extract_tool_result,
    "claude_code.user_prompt": extract_user_prompt,
    "claude_code.api_error": extract_api_error,
}


def validate_event(event):
    """Return (is_valid, reason) for an event."""
    if not isinstance(event, dict):
        return False, "not a dict"

    body = event.get("body")
    if body not in EVENT_TABLE_MAP:
        return False, f"unknown event type: {body}"

    attrs = event.get("attributes", {})
    missing = REQUIRED_FIELDS - set(attrs.keys())
    if missing:
        return False, f"missing fields: {missing}"

    if not attrs.get("user.email"):
        return False, "empty user.email"

    return True, None


FLUSH_THRESHOLD = 50_000  # rows per table before flushing


def ingest_telemetry(con, telemetry_path):
    """Stream-parse JSONL, chunked bulk-insert via DataFrame."""
    buffers = {table: [] for table in EVENT_TABLE_MAP.values()}
    stats = {"total": 0, "valid": 0, "rejected": 0, "by_type": {}}

    logger.info(f"Reading {telemetry_path}...")

    con.execute("BEGIN TRANSACTION")

    with open(telemetry_path) as f:
        for line_num, line in enumerate(f, 1):
            try:
                batch = json.loads(line)
            except json.JSONDecodeError:
                stats["rejected"] += 1
                continue

            for log_event in batch.get("logEvents", []):
                stats["total"] += 1
                event_id = log_event.get("id")

                try:
                    event = json.loads(log_event.get("message", "{}"))
                except json.JSONDecodeError:
                    stats["rejected"] += 1
                    continue

                is_valid, reason = validate_event(event)
                if not is_valid:
                    stats["rejected"] += 1
                    continue

                body = event["body"]
                table = EVENT_TABLE_MAP[body]
                common = extract_common_fields(event)
                common["event_id"] = event_id

                if common["timestamp"] is None:
                    stats["rejected"] += 1
                    continue

                extractor = EXTRACTORS[body]
                row = extractor(event, common)
                buffers[table].append(row)
                stats["valid"] += 1
                stats["by_type"][body] = stats["by_type"].get(body, 0) + 1

                if len(buffers[table]) >= FLUSH_THRESHOLD:
                    _flush_dataframe(con, table, buffers[table])
                    buffers[table] = []

            if line_num % 10000 == 0:
                logger.info(f"  Processed {line_num} batches ({stats['valid']} events)...")

    # Flush remaining
    for table, rows in buffers.items():
        if rows:
            _flush_dataframe(con, table, rows)

    con.execute("COMMIT")

    return stats


def _flush_dataframe(con, table, rows):
    """Bulk-insert rows via DataFrame → DuckDB replacement scan."""
    df = pd.DataFrame(rows)
    columns = list(df.columns)
    col_names = ", ".join(columns)
    con.execute(f"INSERT INTO {table} ({col_names}) SELECT * FROM df")


def load_employees(con, employees_path):
    """Load employees CSV into DuckDB."""
    logger.info(f"Loading employees from {employees_path}...")
    count = 0
    with open(employees_path) as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append((
                row["email"],
                row["full_name"],
                row["practice"],
                row["level"],
                row["location"],
            ))
            count += 1
    con.executemany(
        "INSERT INTO employees (email, full_name, practice, level, location) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    logger.info(f"  Loaded {count} employees")
    return count


def materialize_sessions(con):
    """Build the sessions table from aggregated event data."""
    logger.info("Materializing sessions table...")
    con.execute(SESSIONS_AGGREGATION)
    count = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    logger.info(f"  Materialized {count} sessions")
    return count


def populate_data_quality(con):
    """Query each table for NULL counts and merge with parse failure stats."""
    logger.info("Populating data quality table...")

    # (table, field, is_optional)
    quality_fields = [
        ("api_requests", "input_tokens", False),
        ("api_requests", "output_tokens", False),
        ("api_requests", "cache_read_tokens", False),
        ("api_requests", "cache_creation_tokens", False),
        ("api_requests", "cost_usd", False),
        ("api_requests", "duration_ms", False),
        ("tool_results", "success", False),
        ("tool_results", "duration_ms", False),
        ("tool_results", "result_size_bytes", True),  # optional, ~30% present
        ("user_prompts", "prompt_length", False),
        ("api_errors", "attempt", False),
        ("api_errors", "duration_ms", False),
    ]

    for table, field, is_optional in quality_fields:
        total = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        null_count = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {field} IS NULL"
        ).fetchone()[0]
        parse_failures = _parse_failures.get((table, field), 0)
        con.execute(
            "INSERT INTO data_quality VALUES (?, ?, ?, ?, ?, ?)",
            [table, field, total, null_count, parse_failures, is_optional],
        )

    count = con.execute("SELECT COUNT(*) FROM data_quality").fetchone()[0]
    logger.info(f"  Recorded quality metrics for {count} field checks")


def verify_email_coverage(con):
    """Check that all telemetry emails exist in the employees table."""
    orphaned = con.execute("""
        SELECT DISTINCT user_email FROM (
            SELECT user_email FROM api_requests
            UNION
            SELECT user_email FROM tool_decisions
            UNION
            SELECT user_email FROM tool_results
            UNION
            SELECT user_email FROM user_prompts
            UNION
            SELECT user_email FROM api_errors
        )
        WHERE user_email NOT IN (SELECT email FROM employees)
    """).fetchall()

    if orphaned:
        emails = [r[0] for r in orphaned]
        logger.warning(f"  Found {len(emails)} orphaned emails not in employees table: {emails[:5]}...")
    else:
        logger.info("  All telemetry emails match employees table")

    return [r[0] for r in orphaned]


def run(db_path=DB_PATH, telemetry_path=TELEMETRY_PATH, employees_path=EMPLOYEES_PATH):
    """Run the full ingestion pipeline."""
    _parse_failures.clear()

    # Ensure output dir exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # Remove existing DB for clean run
    db_file = Path(db_path)
    if db_file.exists():
        db_file.unlink()
    wal_file = Path(f"{db_path}.wal")
    if wal_file.exists():
        wal_file.unlink()

    con = duckdb.connect(db_path)

    try:
        # Create tables
        logger.info("Creating tables...")
        for name, ddl in TABLES.items():
            con.execute(ddl)
            logger.info(f"  Created {name}")

        # Load employees
        load_employees(con, employees_path)

        # Ingest telemetry
        stats = ingest_telemetry(con, telemetry_path)

        # Verify email coverage
        verify_email_coverage(con)

        # Materialize sessions
        materialize_sessions(con)

        # Populate data quality
        populate_data_quality(con)

        # Print summary
        logger.info("=== Ingestion Summary ===")
        logger.info(f"  Total events processed: {stats['total']}")
        logger.info(f"  Valid events loaded:    {stats['valid']}")
        logger.info(f"  Rejected events:        {stats['rejected']}")
        for event_type, count in sorted(stats["by_type"].items(), key=lambda x: -x[1]):
            logger.info(f"    {event_type}: {count}")

        # Data quality
        logger.info("=== Data Quality ===")
        for (table, field), count in sorted(_parse_failures.items()):
            logger.info(f"  Parse failures: {table}.{field} = {count}")
        if not _parse_failures:
            logger.info("  No parse failures detected")

        # Table row counts
        logger.info("=== Table Row Counts ===")
        for table in TABLES:
            count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            logger.info(f"  {table}: {count}")

    finally:
        con.close()

    logger.info(f"Database written to {db_path}")


if __name__ == "__main__":
    run()
