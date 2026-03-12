# Claude Code Analytics Platform

## Project
End-to-end analytics platform for Claude Code telemetry data. Ingests CloudWatch-style JSONL events, stores in DuckDB, serves via Streamlit dashboard and FastAPI.

## Architecture
- `src/ingestion/` — Stream-parses nested JSONL into typed DuckDB tables
- `src/analytics/` — Query functions returning DataFrames
- `src/dashboard/` — Streamlit app with 6 view modules in `views/`
- `src/api/` — FastAPI REST endpoints wrapping analytics queries
- `src/ml/` — Forecasting, anomaly detection, clustering
- `tests/` — Unit + integration tests for ingestion pipeline

## Key Decisions
- **No shared events table** — each event type has its own table with denormalized common fields. Avoids unnecessary joins.
- **DuckDB** — columnar, analytics-optimized, zero-config. All queries are analytical aggregations.
- **Email field** — use `attributes.user.email`, NOT `resource.user.email` (always empty).
- **`tool_result_size_bytes`** in raw data maps to `result_size_bytes` in schema.
- **Peak usage** — count `user_prompt` events or sessions, not raw events. Raw events overweight long sessions.
- **Version** is fixed per user, not per session — distribution analysis, not rollout curves.

## Commands
```bash
make setup    # venv + deps + generate data (seed 42) + ingest
make run      # Streamlit dashboard on :8501
make api      # FastAPI on :8000
make test     # pytest
make clean    # remove output/, venv, duckdb files
```

## Data
- Generated via `generate_fake_data.py` with `--seed 42` for reproducibility
- `output/` is gitignored — reviewers run `make setup` to regenerate
- Employee dimension values use full strings: "ML Engineering", "United States", etc.

## Data Quality
- **No silent imputation at ingestion.** Malformed values become NULL, not 0. Real zeros stay 0. Imputation (COALESCE to 0) belongs in analytics queries, only where analytically justified.
- **Booleans are 3-state.** `"true"` → True, `"false"` → False, missing/malformed → NULL. Never coerce unknown into False — it corrupts success rates.
- **`data_quality` table** tracks per-field NULL counts and parse failures. Fields marked `is_optional` (e.g. `result_size_bytes`) are not flagged for high NULL rates.
- **Sessions preserve unknowns.** COUNT-based session fields (num_turns, etc.) COALESCE to 0 on LEFT JOIN miss. SUM-based fields (total_cost, tokens) stay NULL when values are unknown — a session with API calls but no valid costs is NULL, not $0.00.
- **Success rate denominators** use `COUNT(success)` not `COUNT(*)` to exclude unknowns from the rate calculation.

## Performance
- **Bulk insert via DataFrame**, not `executemany`. DuckDB's replacement scan (`INSERT INTO t SELECT * FROM df`) uses vectorized columnar ingestion. Row-by-row `executemany` was 20x slower (248s → 12s for 454K events).
- **Single transaction** for all inserts — one commit, not 94 flushes.
- **`fromisoformat`** over `strptime` for timestamp parsing (~2x faster on Python 3.9).

## Conventions
- Analytics queries go in `src/analytics/queries.py`, return DataFrames
- Dashboard views go in `src/dashboard/views/`, each exports `render()`
- **Parameterized queries everywhere.** `build_where_clause()` and `FilterParams.where()` return `(clause, params)` tuples with `?` placeholders. Pass `params` to `query(sql, params)`. Never interpolate user values into SQL strings.
- `PYTHONPATH` is set via Makefile for Streamlit/uvicorn commands
