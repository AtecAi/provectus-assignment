"""Cost forecasting using statsmodels."""

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from src.analytics.queries import daily_cost


def forecast_daily_cost(forecast_days=14, db_path="output/analytics.duckdb", data=None):
    """Forecast daily cost using Holt-Winters exponential smoothing."""
    df = data.copy() if data is not None else daily_cost(db_path)
    if df.empty:
        return pd.DataFrame(columns=["date", "actual", "forecast", "lower", "upper"])

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    # Backfill missing days with 0 cost so the time series is contiguous
    full_range = pd.date_range(start=df.index.min(), end=df.index.max(), freq="D")
    df = df.reindex(full_range, fill_value=0.0)
    df.index.name = "date"

    series = df["daily_cost"]

    # Narrow filters can produce a single remaining day; fall back to a flat forecast.
    if len(series) < 2:
        actual_df = pd.DataFrame({
            "date": series.index,
            "actual": series.values,
            "forecast": series.values,
            "lower": np.nan,
            "upper": np.nan,
        })
        forecast_index = pd.date_range(
            start=series.index[-1] + pd.Timedelta(days=1),
            periods=forecast_days,
            freq="D",
        )
        forecast_df = pd.DataFrame({
            "date": forecast_index,
            "actual": np.nan,
            "forecast": float(series.iloc[-1]),
            "lower": np.nan,
            "upper": np.nan,
        })
        return pd.concat([actual_df, forecast_df], ignore_index=True)

    # Fit model — use additive trend, no seasonality (too few data points for weekly)
    model = ExponentialSmoothing(
        series,
        trend="add",
        seasonal=None,
        initialization_method="estimated",
    ).fit(optimized=True)

    # Forecast
    forecast_index = pd.date_range(
        start=series.index[-1] + pd.Timedelta(days=1),
        periods=forecast_days,
        freq="D",
    )
    forecast_values = model.forecast(forecast_days)

    # Build result DataFrame
    actual_df = pd.DataFrame({
        "date": series.index,
        "actual": series.values,
        "forecast": model.fittedvalues.values,
    })

    forecast_df = pd.DataFrame({
        "date": forecast_index,
        "actual": np.nan,
        "forecast": forecast_values.values,
    })

    # Confidence intervals (approximate using residual std)
    residuals = series - model.fittedvalues
    std = residuals.std()
    forecast_df["lower"] = forecast_df["forecast"] - 1.96 * std
    forecast_df["upper"] = forecast_df["forecast"] + 1.96 * std
    actual_df["lower"] = np.nan
    actual_df["upper"] = np.nan

    result = pd.concat([actual_df, forecast_df], ignore_index=True)
    return result
