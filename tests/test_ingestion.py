"""Tests for the ingestion pipeline."""

import json
import os
import tempfile

import duckdb
import pytest

from src.ingestion.pipeline import (
    safe_int,
    safe_float,
    safe_bool,
    parse_timestamp,
    validate_event,
    extract_common_fields,
    extract_api_request,
    extract_tool_result,
    ingest_telemetry,
    load_employees,
    materialize_sessions,
    run,
)


# ---------------------------------------------------------------------------
# Unit tests: type casting
# ---------------------------------------------------------------------------

class TestSafeCasting:
    def test_safe_int_valid(self):
        assert safe_int("42") == 42

    def test_safe_int_float_string(self):
        # int() can't parse "3.14" directly — returns None
        assert safe_int("3.14") is None

    def test_safe_int_none(self):
        assert safe_int(None) is None

    def test_safe_int_empty(self):
        assert safe_int("") is None

    def test_safe_int_custom_default(self):
        assert safe_int("bad", default=-1) == -1

    def test_safe_int_zero(self):
        assert safe_int("0") == 0

    def test_safe_float_valid(self):
        assert safe_float("3.14") == pytest.approx(3.14)

    def test_safe_float_none(self):
        assert safe_float(None) is None

    def test_safe_float_empty(self):
        assert safe_float("") is None

    def test_safe_float_zero(self):
        assert safe_float("0.0") == 0.0

    def test_safe_float_inf(self):
        assert safe_float("inf") is None

    def test_safe_float_negative_inf(self):
        assert safe_float("-inf") is None

    def test_safe_float_nan(self):
        assert safe_float("nan") is None

    def test_safe_float_python_inf(self):
        assert safe_float(float("inf")) is None

    def test_safe_float_python_nan(self):
        assert safe_float(float("nan")) is None


class TestSafeBool:
    def test_true_string(self):
        assert safe_bool("true") is True

    def test_false_string(self):
        assert safe_bool("false") is False

    def test_none(self):
        assert safe_bool(None) is None

    def test_malformed(self):
        assert safe_bool("yes") is None

    def test_empty(self):
        assert safe_bool("") is None

    def test_case_insensitive(self):
        assert safe_bool("True") is True
        assert safe_bool("FALSE") is False

    def test_python_bool_true(self):
        # json.loads() produces Python True/False
        assert safe_bool(True) is True

    def test_python_bool_false(self):
        assert safe_bool(False) is False


class TestParseTimestamp:
    def test_valid(self):
        ts = parse_timestamp("2025-12-03T00:06:00.000Z")
        assert ts is not None
        assert ts.year == 2025
        assert ts.month == 12

    def test_invalid(self):
        assert parse_timestamp("not-a-timestamp") is None

    def test_none(self):
        assert parse_timestamp(None) is None


# ---------------------------------------------------------------------------
# Unit tests: validation
# ---------------------------------------------------------------------------

class TestValidation:
    def _make_event(self, **overrides):
        event = {
            "body": "claude_code.api_request",
            "attributes": {
                "event.timestamp": "2025-12-03T00:06:00.000Z",
                "session.id": "abc-123",
                "user.email": "test@example.com",
                "event.name": "api_request",
                "model": "claude-opus-4-6",
                "input_tokens": "100",
                "output_tokens": "200",
                "cache_read_tokens": "0",
                "cache_creation_tokens": "0",
                "cost_usd": "0.05",
                "duration_ms": "5000",
            },
            "scope": {"name": "com.anthropic.claude_code.events", "version": "2.1.50"},
            "resource": {"host.arch": "arm64", "os.type": "darwin"},
        }
        if "body" in overrides:
            event["body"] = overrides.pop("body")
        if "attributes" in overrides:
            event["attributes"].update(overrides.pop("attributes"))
        event.update(overrides)
        return event

    def test_valid_event(self):
        is_valid, reason = validate_event(self._make_event())
        assert is_valid
        assert reason is None

    def test_unknown_event_type(self):
        is_valid, reason = validate_event(self._make_event(body="unknown.type"))
        assert not is_valid
        assert "unknown event type" in reason

    def test_missing_session_id(self):
        event = self._make_event()
        del event["attributes"]["session.id"]
        is_valid, reason = validate_event(event)
        assert not is_valid

    def test_empty_email(self):
        event = self._make_event(attributes={"user.email": ""})
        is_valid, reason = validate_event(event)
        assert not is_valid

    def test_not_a_dict(self):
        is_valid, reason = validate_event("not a dict")
        assert not is_valid


# ---------------------------------------------------------------------------
# Unit tests: field extraction
# ---------------------------------------------------------------------------

class TestExtraction:
    def _make_event(self):
        return {
            "body": "claude_code.api_request",
            "attributes": {
                "event.timestamp": "2025-12-03T10:30:00.500Z",
                "session.id": "sess-001",
                "user.email": "dev@example.com",
                "terminal.type": "vscode",
                "organization.id": "org-1",
                "event.name": "api_request",
                "model": "claude-opus-4-6",
                "input_tokens": "150",
                "output_tokens": "300",
                "cache_read_tokens": "5000",
                "cache_creation_tokens": "1000",
                "cost_usd": "0.071",
                "duration_ms": "10230",
            },
            "scope": {"version": "2.1.50"},
            "resource": {"host.arch": "arm64", "os.type": "darwin"},
        }

    def test_common_fields(self):
        common = extract_common_fields(self._make_event())
        assert common["session_id"] == "sess-001"
        assert common["user_email"] == "dev@example.com"
        assert common["terminal_type"] == "vscode"
        assert common["timestamp"].hour == 10

    def test_api_request_fields(self):
        event = self._make_event()
        common = extract_common_fields(event)
        row = extract_api_request(event, common)
        assert row["model"] == "claude-opus-4-6"
        assert row["input_tokens"] == 150
        assert row["output_tokens"] == 300
        assert row["cost_usd"] == pytest.approx(0.071)

    def test_tool_result_size_bytes_rename(self):
        event = {
            "body": "claude_code.tool_result",
            "attributes": {
                "event.timestamp": "2025-12-03T10:30:00.500Z",
                "session.id": "sess-001",
                "user.email": "dev@example.com",
                "event.name": "tool_result",
                "tool_name": "Bash",
                "success": "true",
                "duration_ms": "500",
                "decision_source": "config",
                "decision_type": "accept",
                "tool_result_size_bytes": "12345",
            },
            "scope": {"version": "2.1.50"},
            "resource": {"host.arch": "arm64", "os.type": "darwin"},
        }
        common = extract_common_fields(event)
        row = extract_tool_result(event, common)
        assert row["result_size_bytes"] == 12345

    def test_tool_result_size_bytes_absent(self):
        event = {
            "body": "claude_code.tool_result",
            "attributes": {
                "event.timestamp": "2025-12-03T10:30:00.500Z",
                "session.id": "sess-001",
                "user.email": "dev@example.com",
                "event.name": "tool_result",
                "tool_name": "Read",
                "success": "true",
                "duration_ms": "30",
                "decision_source": "config",
                "decision_type": "accept",
            },
            "scope": {"version": "2.1.50"},
            "resource": {"host.arch": "arm64", "os.type": "darwin"},
        }
        common = extract_common_fields(event)
        row = extract_tool_result(event, common)
        assert row["result_size_bytes"] is None

    def test_tool_result_size_bytes_zero(self):
        """Real zero (0) stays 0, not NULL."""
        event = {
            "body": "claude_code.tool_result",
            "attributes": {
                "event.timestamp": "2025-12-03T10:30:00.500Z",
                "session.id": "sess-001",
                "user.email": "dev@example.com",
                "event.name": "tool_result",
                "tool_name": "Bash",
                "success": "true",
                "duration_ms": "30",
                "tool_result_size_bytes": "0",
            },
            "scope": {"version": "2.1.50"},
            "resource": {"host.arch": "arm64", "os.type": "darwin"},
        }
        common = extract_common_fields(event)
        row = extract_tool_result(event, common)
        assert row["result_size_bytes"] == 0


# ---------------------------------------------------------------------------
# Unit tests: malformed fields → NULL, not 0
# ---------------------------------------------------------------------------

class TestMalformedFields:
    """Events with malformed numerics should be kept but have NULL metric fields."""

    def test_malformed_numerics_become_null(self):
        event = {
            "body": "claude_code.api_request",
            "attributes": {
                "event.timestamp": "2025-12-03T00:06:00.000Z",
                "session.id": "abc-123",
                "user.email": "test@example.com",
                "model": "claude-opus-4-6",
                "input_tokens": "not_a_number",
                "output_tokens": "also_bad",
                "cache_read_tokens": "",
                "cache_creation_tokens": "garbage",
                "cost_usd": "free",
                "duration_ms": "fast",
            },
            "scope": {"version": "2.1.50"},
            "resource": {"host.arch": "arm64", "os.type": "darwin"},
        }
        common = extract_common_fields(event)
        row = extract_api_request(event, common)
        assert row["input_tokens"] is None
        assert row["output_tokens"] is None
        assert row["cache_read_tokens"] is None
        assert row["cache_creation_tokens"] is None
        assert row["cost_usd"] is None
        assert row["duration_ms"] is None

    def test_valid_zero_stays_zero(self):
        event = {
            "body": "claude_code.api_request",
            "attributes": {
                "event.timestamp": "2025-12-03T00:06:00.000Z",
                "session.id": "abc-123",
                "user.email": "test@example.com",
                "model": "claude-opus-4-6",
                "input_tokens": "0",
                "output_tokens": "0",
                "cache_read_tokens": "0",
                "cache_creation_tokens": "0",
                "cost_usd": "0.0",
                "duration_ms": "0",
            },
            "scope": {"version": "2.1.50"},
            "resource": {"host.arch": "arm64", "os.type": "darwin"},
        }
        common = extract_common_fields(event)
        row = extract_api_request(event, common)
        assert row["input_tokens"] == 0
        assert row["output_tokens"] == 0
        assert row["cache_read_tokens"] == 0
        assert row["cache_creation_tokens"] == 0
        assert row["cost_usd"] == 0.0
        assert row["duration_ms"] == 0

    def test_missing_success_is_none(self):
        """Missing boolean success → None, not False."""
        event = {
            "body": "claude_code.tool_result",
            "attributes": {
                "event.timestamp": "2025-12-03T00:06:00.000Z",
                "session.id": "abc-123",
                "user.email": "test@example.com",
                "tool_name": "Bash",
                "duration_ms": "100",
            },
            "scope": {"version": "2.1.50"},
            "resource": {"host.arch": "arm64", "os.type": "darwin"},
        }
        common = extract_common_fields(event)
        row = extract_tool_result(event, common)
        assert row["success"] is None

    def test_malformed_success_is_none(self):
        """Malformed boolean success → None, not False."""
        event = {
            "body": "claude_code.tool_result",
            "attributes": {
                "event.timestamp": "2025-12-03T00:06:00.000Z",
                "session.id": "abc-123",
                "user.email": "test@example.com",
                "tool_name": "Bash",
                "success": "yes",
                "duration_ms": "100",
            },
            "scope": {"version": "2.1.50"},
            "resource": {"host.arch": "arm64", "os.type": "darwin"},
        }
        common = extract_common_fields(event)
        row = extract_tool_result(event, common)
        assert row["success"] is None


# ---------------------------------------------------------------------------
# Integration test: full pipeline with small dataset
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_pipeline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Generate small dataset
            telemetry_path = os.path.join(tmpdir, "telemetry_logs.jsonl")
            employees_path = os.path.join(tmpdir, "employees.csv")
            db_path = os.path.join(tmpdir, "test.duckdb")

            # Write employees
            with open(employees_path, "w") as f:
                f.write("email,full_name,practice,level,location\n")
                f.write("alice@example.com,Alice Smith,ML Engineering,L5,United States\n")

            # Write telemetry — 1 batch with 3 events
            events = []
            base_event = {
                "attributes": {
                    "event.timestamp": "2025-12-03T10:00:00.000Z",
                    "session.id": "test-session-1",
                    "user.email": "alice@example.com",
                    "terminal.type": "vscode",
                    "organization.id": "org-1",
                },
                "scope": {"version": "2.1.50"},
                "resource": {"host.arch": "arm64", "os.type": "darwin"},
            }

            # user_prompt
            prompt_event = {**base_event, "body": "claude_code.user_prompt"}
            prompt_event["attributes"] = {**base_event["attributes"], "event.name": "user_prompt", "prompt": "<REDACTED>", "prompt_length": "100"}
            events.append(prompt_event)

            # api_request
            api_event = {**base_event, "body": "claude_code.api_request"}
            api_event["attributes"] = {
                **base_event["attributes"],
                "event.name": "api_request",
                "model": "claude-opus-4-6",
                "input_tokens": "50", "output_tokens": "200",
                "cache_read_tokens": "1000", "cache_creation_tokens": "500",
                "cost_usd": "0.05", "duration_ms": "8000",
                "event.timestamp": "2025-12-03T10:00:01.000Z",
            }
            events.append(api_event)

            # tool_result
            tool_event = {**base_event, "body": "claude_code.tool_result"}
            tool_event["attributes"] = {
                **base_event["attributes"],
                "event.name": "tool_result",
                "tool_name": "Read", "success": "true", "duration_ms": "30",
                "decision_source": "config", "decision_type": "accept",
                "event.timestamp": "2025-12-03T10:00:10.000Z",
            }
            events.append(tool_event)

            batch = {
                "messageType": "DATA_MESSAGE",
                "logGroup": "/claude-code/telemetry",
                "logStream": "otel-collector",
                "logEvents": [
                    {"id": str(i), "timestamp": 1000000 + i, "message": json.dumps(e)}
                    for i, e in enumerate(events)
                ],
            }

            with open(telemetry_path, "w") as f:
                f.write(json.dumps(batch) + "\n")

            # Run pipeline
            run(db_path=db_path, telemetry_path=telemetry_path, employees_path=employees_path)

            # Verify
            con = duckdb.connect(db_path, read_only=True)
            try:
                assert con.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 1
                assert con.execute("SELECT COUNT(*) FROM user_prompts").fetchone()[0] == 1
                assert con.execute("SELECT COUNT(*) FROM api_requests").fetchone()[0] == 1
                assert con.execute("SELECT COUNT(*) FROM tool_results").fetchone()[0] == 1
                assert con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1

                # Check session aggregation
                session = con.execute("SELECT * FROM sessions").fetchone()
                assert session is not None
                assert session[1] == "alice@example.com"  # user_email
                assert session[5] == 1  # num_turns
                assert session[6] == 1  # num_api_calls
                assert session[7] == 1  # num_tool_uses

                # Check data quality table
                dq_count = con.execute("SELECT COUNT(*) FROM data_quality").fetchone()[0]
                assert dq_count > 0

                # No parse failures expected in clean data
                failures = con.execute(
                    "SELECT SUM(parse_failure_count) FROM data_quality"
                ).fetchone()[0]
                assert failures == 0
            finally:
                con.close()
