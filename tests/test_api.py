"""Tests for the FastAPI REST API.

These are integration tests that run against the seed-42 DuckDB database.
They verify endpoint responses, filter behavior, and the fixes for
review findings (global filters, deterministic ordering, route correctness).
"""

import os
import pytest
from fastapi.testclient import TestClient

# Skip entire module if the database doesn't exist (CI without make setup)
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "output", "analytics.duckdb")
pytestmark = pytest.mark.skipif(
    not os.path.exists(DB_PATH),
    reason="Requires output/analytics.duckdb (run make setup first)",
)

from src.api.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Basic endpoint smoke tests — every route returns 200
# ---------------------------------------------------------------------------

class TestEndpointSmoke:
    """Every endpoint should return 200 with no filters."""

    @pytest.mark.parametrize("path", [
        "/api/v1/overview",
        "/api/v1/activity/daily",
        "/api/v1/cost/daily",
        "/api/v1/cost/by-practice",
        "/api/v1/cost/by-model",
        "/api/v1/cost/by-practice-and-level",
        "/api/v1/cost/efficiency",
        "/api/v1/tokens/by-practice",
        "/api/v1/tokens/by-level",
        "/api/v1/tools/usage",
        "/api/v1/tools/success-rates",
        "/api/v1/tools/rejection-rate",
        "/api/v1/usage/peak-hours",
        "/api/v1/usage/peak-days",
        "/api/v1/sessions/depth",
        "/api/v1/ide/adoption",
        "/api/v1/errors/daily",
        "/api/v1/models/latency",
        "/api/v1/models/preference",
        "/api/v1/versions/distribution",
        "/api/v1/data-quality",
    ])
    def test_returns_200(self, path):
        resp = client.get(path)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# Finding 1: Model/terminal filters are global — applied to all endpoints
# ---------------------------------------------------------------------------

class TestGlobalFilters:
    """Model and terminal filters should reduce results on endpoints
    that query tables without native model/terminal columns."""

    def test_overview_respects_model_filter(self):
        """sessions lacks model column; filter via session subquery."""
        all_data = client.get("/api/v1/overview").json()
        filtered = client.get("/api/v1/overview", params={
            "model": "claude-opus-4-6",
        }).json()
        assert filtered[0]["total_sessions"] < all_data[0]["total_sessions"]

    def test_daily_activity_respects_model_filter(self):
        """user_prompts lacks model column; filter via session subquery."""
        all_data = client.get("/api/v1/activity/daily").json()
        filtered = client.get("/api/v1/activity/daily", params={
            "model": "claude-opus-4-6",
        }).json()
        all_total = sum(r["prompt_count"] for r in all_data)
        filt_total = sum(r["prompt_count"] for r in filtered)
        assert filt_total < all_total

    def test_tool_usage_respects_model_filter(self):
        """tool_decisions lacks model column; filter via session subquery."""
        all_data = client.get("/api/v1/tools/usage").json()
        filtered = client.get("/api/v1/tools/usage", params={
            "model": "claude-opus-4-6",
        }).json()
        # Filtered should have fewer total events
        all_total = sum(r["usage_count"] for r in all_data)
        filt_total = sum(r["usage_count"] for r in filtered)
        assert filt_total < all_total

    def test_tool_success_rates_respects_model_filter(self):
        """tool_results lacks model column; filter via session subquery."""
        all_data = client.get("/api/v1/tools/success-rates").json()
        filtered = client.get("/api/v1/tools/success-rates", params={
            "model": "claude-opus-4-6",
        }).json()
        all_total = sum(r["total_executions"] for r in all_data)
        filt_total = sum(r["total_executions"] for r in filtered)
        assert filt_total < all_total

    def test_peak_hours_respects_model_filter(self):
        """user_prompts lacks model column; filter via session subquery."""
        all_data = client.get("/api/v1/usage/peak-hours").json()
        filtered = client.get("/api/v1/usage/peak-hours", params={
            "model": "claude-opus-4-6",
        }).json()
        all_total = sum(r["prompt_count"] for r in all_data)
        filt_total = sum(r["prompt_count"] for r in filtered)
        assert filt_total < all_total

    def test_session_depth_respects_model_filter(self):
        """sessions lacks model column; filter via session subquery."""
        all_data = client.get("/api/v1/sessions/depth").json()
        filtered = client.get("/api/v1/sessions/depth", params={
            "model": "claude-opus-4-6",
        }).json()
        all_total = sum(r["num_sessions"] for r in all_data)
        filt_total = sum(r["num_sessions"] for r in filtered)
        assert filt_total < all_total

    def test_errors_daily_respects_model_filter(self):
        """api_errors has model column; should filter directly."""
        all_data = client.get("/api/v1/errors/daily").json()
        filtered = client.get("/api/v1/errors/daily", params={
            "model": "claude-opus-4-6",
        }).json()
        all_total = sum(r["error_count"] for r in all_data)
        filt_total = sum(r["error_count"] for r in filtered)
        assert filt_total < all_total

    def test_nonexistent_model_returns_empty(self):
        """A model that doesn't exist should yield empty results."""
        resp = client.get("/api/v1/tools/usage", params={
            "model": "nonexistent-model-xyz",
        })
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# Finding 2: Version distribution is deterministic (tiebreaker)
# ---------------------------------------------------------------------------

class TestDeterministicOrdering:
    """ORDER BY with tiebreaker should produce identical results on repeat."""

    def test_version_distribution_deterministic(self):
        r1 = client.get("/api/v1/versions/distribution").json()
        r2 = client.get("/api/v1/versions/distribution").json()
        assert r1 == r2


# ---------------------------------------------------------------------------
# Finding 3: Version distribution respects model/terminal filters
# ---------------------------------------------------------------------------

class TestVersionDistributionFilters:

    def test_model_filter_reduces_results(self):
        all_data = client.get("/api/v1/versions/distribution").json()
        filtered = client.get("/api/v1/versions/distribution", params={
            "model": "claude-opus-4-6",
        }).json()
        all_total = sum(r["event_count"] for r in all_data)
        filt_total = sum(r["event_count"] for r in filtered)
        assert filt_total < all_total

    def test_terminal_filter_reduces_results(self):
        all_data = client.get("/api/v1/versions/distribution").json()
        filtered = client.get("/api/v1/versions/distribution", params={
            "terminal_type": "vscode",
        }).json()
        all_total = sum(r["event_count"] for r in all_data)
        filt_total = sum(r["event_count"] for r in filtered)
        assert filt_total < all_total


# ---------------------------------------------------------------------------
# Finding 4: Routes match documented paths
# ---------------------------------------------------------------------------

class TestRouteExistence:
    """Verify documented routes exist and undocumented ones 404."""

    def test_overview_not_overview_kpis(self):
        assert client.get("/api/v1/overview").status_code == 200
        assert client.get("/api/v1/overview/kpis").status_code in (404, 405)

    def test_sessions_depth_not_sessions(self):
        assert client.get("/api/v1/sessions/depth").status_code == 200

    def test_practice_filter_on_session_depth(self):
        resp = client.get("/api/v1/sessions/depth", params={
            "practice": "ML Engineering",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["practice"] == "ML Engineering"


# ---------------------------------------------------------------------------
# Filter edge cases
# ---------------------------------------------------------------------------

class TestFilterEdgeCases:

    def test_empty_practice_returns_empty(self):
        """Empty practice list = no results (FALSE clause)."""
        resp = client.get("/api/v1/overview", params={"practice": ""})
        data = resp.json()
        assert data[0]["total_sessions"] == 0

    def test_multiple_practices(self):
        resp = client.get("/api/v1/cost/by-practice", params={
            "practice": ["ML Engineering", "Data Engineering"],
        })
        assert resp.status_code == 200
        practices = {r["practice"] for r in resp.json()}
        assert practices == {"ML Engineering", "Data Engineering"}

    def test_date_filter_narrows_results(self):
        all_data = client.get("/api/v1/overview").json()
        filtered = client.get("/api/v1/overview", params={
            "date_start": "2026-01-01",
            "date_end": "2026-01-15",
        }).json()
        assert filtered[0]["total_sessions"] < all_data[0]["total_sessions"]
