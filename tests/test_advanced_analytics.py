"""Tests for Advanced Analytics filtered data loaders and ML edge cases."""

from datetime import date
import os

import pandas as pd
import pytest

from src.analytics.queries import query
from src.dashboard.views.advanced_analytics import (
    _load_filtered_daily_cost,
    _load_filtered_sessions,
    _load_filtered_user_features,
)
from src.ml.anomaly import detect_session_anomalies
from src.ml.clustering import cluster_users
from src.ml.forecasting import forecast_daily_cost

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "output", "analytics.duckdb")
pytestmark = pytest.mark.skipif(
    not os.path.exists(DB_PATH),
    reason="Requires output/analytics.duckdb (run make setup first)",
)


def _all_filters(**overrides):
    """Build a dashboard filter dict equivalent to selecting 'All' in the UI."""
    base = {
        "date_start": date(2025, 12, 3),
        "date_end": date(2026, 2, 1),
        "practices": query("SELECT DISTINCT practice FROM employees ORDER BY practice")["practice"].tolist(),
        "levels": query("SELECT DISTINCT level FROM employees ORDER BY level")["level"].tolist(),
        "locations": query("SELECT DISTINCT location FROM employees ORDER BY location")["location"].tolist(),
        "models": query("SELECT DISTINCT model FROM api_requests WHERE model IS NOT NULL ORDER BY model")["model"].tolist(),
        "terminals": query("SELECT DISTINCT terminal_type FROM api_requests WHERE terminal_type IS NOT NULL ORDER BY terminal_type")["terminal_type"].tolist(),
    }
    base.update(overrides)
    return base


class TestAdvancedAnalyticsFilterLoaders:

    def test_forecast_loader_respects_model_filter(self):
        all_data = _load_filtered_daily_cost(_all_filters())
        filtered = _load_filtered_daily_cost(_all_filters(models=["claude-opus-4-6"]))
        assert filtered["daily_cost"].sum() < all_data["daily_cost"].sum()

    def test_session_loader_respects_model_filter(self):
        all_data = _load_filtered_sessions(_all_filters())
        filtered = _load_filtered_sessions(_all_filters(models=["claude-opus-4-6"]))
        assert len(filtered) < len(all_data)

    def test_cluster_loader_respects_model_filter(self):
        all_data = _load_filtered_user_features(_all_filters())
        filtered = _load_filtered_user_features(_all_filters(models=["claude-opus-4-6"]))
        assert filtered["total_sessions"].sum() < all_data["total_sessions"].sum()


class TestMlEdgeCases:

    def test_forecast_handles_single_day_input(self):
        df = pd.DataFrame([{"date": "2026-01-01", "daily_cost": 42.0}])
        result = forecast_daily_cost(data=df, forecast_days=3)
        assert len(result) == 4
        assert result["forecast"].iloc[-1] == 42.0

    def test_anomaly_detection_handles_single_row(self):
        df = pd.DataFrame([{
            "session_id": "s1",
            "user_email": "u@example.com",
            "start_time": "2026-01-01T00:00:00",
            "num_turns": 3,
            "num_api_calls": 4,
            "num_tool_uses": 2,
            "total_cost": 1.2,
            "duration_sec": 30,
            "error_count": 0,
            "practice": "ML Engineering",
            "level": "L5",
            "location": "United States",
        }])
        result = detect_session_anomalies(data=df)
        assert len(result) == 1
        assert not bool(result["is_anomaly"].iloc[0])
        assert result["anomaly_score"].iloc[0] == 0.0

    def test_clustering_handles_single_row(self):
        df = pd.DataFrame([{
            "user_email": "u@example.com",
            "practice": "ML Engineering",
            "level": "L5",
            "location": "United States",
            "total_sessions": 2,
            "avg_turns_per_session": 3.0,
            "avg_api_calls_per_session": 4.0,
            "avg_tool_uses_per_session": 1.0,
            "avg_cost_per_session": 0.5,
            "total_cost": 1.0,
            "avg_duration_sec": 20.0,
            "total_errors": 0,
        }])
        result = cluster_users(data=df)
        assert len(result) == 1
        assert result["cluster"].iloc[0] == "0"
