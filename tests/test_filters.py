"""Tests for dashboard filter building and session model filter."""

from datetime import date
import pytest

from src.dashboard.filters import build_where_clause, build_session_model_filter


def _make_filters(**overrides):
    """Create a filter dict with sensible defaults."""
    base = {
        "date_start": date(2025, 12, 3),
        "date_end": date(2026, 2, 1),
        "practices": ["ML Engineering", "Data Engineering"],
        "levels": ["L5", "L6"],
        "locations": ["United States"],
        "models": ["claude-opus-4-6"],
        "terminals": ["vscode"],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# build_where_clause
# ---------------------------------------------------------------------------

class TestBuildWhereClause:

    def test_includes_date_range(self):
        clause, params = build_where_clause(_make_filters())
        assert "a.timestamp >= ?" in clause
        assert "a.timestamp <= ?" in clause
        assert "2025-12-03" in params
        assert "2026-02-01 23:59:59" in params

    def test_includes_practice_level_location(self):
        clause, params = build_where_clause(_make_filters())
        assert "e.practice IN (?, ?)" in clause
        assert "e.level IN (?, ?)" in clause
        assert "e.location IN (?)" in clause
        assert "ML Engineering" in params
        assert "L5" in params

    def test_empty_practice_yields_false(self):
        clause, _ = build_where_clause(_make_filters(practices=[]))
        assert "FALSE" in clause

    def test_model_col_included_when_specified(self):
        clause, params = build_where_clause(
            _make_filters(), model_col="a.model"
        )
        assert "a.model IN (?)" in clause
        assert "claude-opus-4-6" in params

    def test_model_col_omitted_when_not_specified(self):
        clause, params = build_where_clause(_make_filters())
        assert "model" not in clause.lower()
        assert "claude-opus-4-6" not in params

    def test_terminal_col_included_when_specified(self):
        clause, params = build_where_clause(
            _make_filters(), terminal_col="a.terminal_type"
        )
        assert "a.terminal_type IN (?)" in clause
        assert "vscode" in params

    def test_empty_model_yields_false(self):
        clause, _ = build_where_clause(
            _make_filters(models=[]), model_col="a.model"
        )
        assert "FALSE" in clause

    def test_custom_aliases(self):
        clause, _ = build_where_clause(
            _make_filters(),
            timestamp_col="tr.timestamp",
            employee_alias="emp",
        )
        assert "tr.timestamp >= ?" in clause
        assert "emp.practice" in clause

    def test_params_are_correctly_ordered(self):
        filters = _make_filters(
            practices=["P1"], levels=["L1"], locations=["US"],
            models=["m1"], terminals=["t1"],
        )
        _, params = build_where_clause(
            filters, model_col="a.model", terminal_col="a.terminal_type"
        )
        # date_start, date_end, practice, level, location, model, terminal
        assert params == [
            "2025-12-03", "2026-02-01 23:59:59",
            "P1", "L1", "US", "m1", "t1",
        ]


# ---------------------------------------------------------------------------
# build_session_model_filter
# ---------------------------------------------------------------------------

class TestBuildSessionModelFilter:

    def test_returns_none_when_no_model_or_terminal(self):
        sub, params = build_session_model_filter(
            _make_filters(models=None, terminals=None)
        )
        assert sub is None
        assert params == []

    def test_returns_subquery_for_model(self):
        sub, params = build_session_model_filter(
            _make_filters(terminals=None)
        )
        assert sub is not None
        assert "SELECT DISTINCT session_id FROM api_requests" in sub
        assert "model IN (?)" in sub
        assert params == ["claude-opus-4-6"]

    def test_returns_subquery_for_terminal(self):
        sub, params = build_session_model_filter(
            _make_filters(models=None)
        )
        assert "terminal_type IN (?)" in sub
        assert params == ["vscode"]

    def test_returns_subquery_for_both(self):
        sub, params = build_session_model_filter(_make_filters())
        assert "model IN (?)" in sub
        assert "terminal_type IN (?)" in sub
        assert params == ["claude-opus-4-6", "vscode"]

    def test_empty_model_list_yields_false(self):
        sub, _ = build_session_model_filter(_make_filters(models=[]))
        assert "FALSE" in sub

    def test_empty_terminal_list_yields_false(self):
        sub, _ = build_session_model_filter(_make_filters(terminals=[]))
        assert "FALSE" in sub

    def test_multiple_models(self):
        sub, params = build_session_model_filter(
            _make_filters(models=["m1", "m2", "m3"], terminals=None)
        )
        assert "model IN (?, ?, ?)" in sub
        assert params == ["m1", "m2", "m3"]
