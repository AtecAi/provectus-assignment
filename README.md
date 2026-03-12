# Claude Code Usage Analytics Platform

An end-to-end analytics platform that ingests Claude Code telemetry data, stores it in a columnar database, and surfaces developer usage patterns through an interactive dashboard and REST API. Built for the Provectus technical assessment.

**What it answers:** How are 100 engineers using Claude Code? What does it cost? Which tools fail? Who are the power users? Where are the anomalies?

## Deliverables Map

| Assignment Requirement | Location |
|----------------------|----------|
| Source code with commit history | This repository |
| README with setup + architecture + dependencies | This file |
| Insights presentation (3-5 slides) | [`docs/Analytics_Result.pdf`](docs/Analytics_Result.pdf) |
| LLM usage log | [LLM Usage section above](#llm-usage) + [`docs/llm-engineering/Claude-Code-Sessions-Log.md`](docs/llm-engineering/Claude-Code-Sessions-Log.md) |
| Technical specification | [`docs/llm-engineering/SPEC.md`](docs/llm-engineering/SPEC.md) |
| Security findings | [`docs/known-limitations.md`](docs/known-limitations.md) |
| Engineering learnings | [`docs/llm-engineering/Compound-Engineering.md`](docs/llm-engineering/Compound-Engineering.md) |

---

## Quick Start

Prerequisites: Python 3.9+, `make`

```bash
git clone <repo-url> && cd provectus
make setup    # creates venv, installs deps, generates data (seed 42), ingests into DuckDB
make run      # launches Streamlit dashboard on http://localhost:8501
```

That's it. `make setup` takes ~30 seconds. The dataset is deterministic (seed 42) — every reviewer sees identical data.

Other commands:

```bash
make api      # FastAPI REST API on http://localhost:8000
make test     # 101 pytest tests
make clean    # remove output/, venv, duckdb files
```

<details>
<summary><strong>Windows (no make)</strong></summary>

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python generate_fake_data.py --num-users 100 --num-sessions 5000 --days 60 --seed 42
.\.venv\Scripts\python -m src.ingestion.pipeline
$env:PYTHONPATH = "."
.\.venv\Scripts\python -m streamlit run src/dashboard/app.py
```
</details>

---

## Architecture

```
telemetry_logs.jsonl (500MB, nested JSONL)
        │
        ▼
┌─────────────────┐
│    Ingestion     │  Stream-parse → validate → bulk insert (DataFrame)
│   pipeline.py    │  454K events in ~12s
└────────┬────────┘
         ▼
┌─────────────────┐
│     DuckDB      │  6 tables: api_requests, tool_decisions, tool_results,
│  analytics.db   │  user_prompts, api_errors, sessions (materialized)
└──┬─────────┬────┘  + employees (from CSV) + data_quality
   │         │
   ▼         ▼
┌───────┐ ┌───────┐
│ Streamlit │ │ FastAPI │  6 dashboard views, 20+ API endpoints
│  :8501    │ │  :8000  │  Global filters: date, practice, level, location, model, IDE
└───────┘ └───────┘
   │
   ▼
┌─────────────────┐
│    ML Layer     │  Cost forecasting (Holt-Winters), anomaly detection
│   src/ml/       │  (Isolation Forest), user clustering (K-Means)
└─────────────────┘
```

### Why DuckDB?

Every query in this platform is an analytical aggregation — `GROUP BY`, `SUM`, `COUNT DISTINCT`, percentiles. DuckDB is columnar and optimized for exactly this. Zero config, single file, no server. SQLite would work but is row-oriented; DuckDB is 10-50x faster on analytical queries.

### Why no shared events table?

Each event type (api_request, tool_result, user_prompt, etc.) has its own table with common fields denormalized. Every analytics query targets one event type and joins with `employees`. A shared base table would add a join to every query with no benefit. Column duplication is negligible in columnar storage.

---

## The Dashboard

Six views, each designed for a different stakeholder question:

| View | What it shows | Who cares |
|------|--------------|-----------|
| **Overview** | KPIs, daily activity, data quality | Everyone |
| **Cost & Tokens** | Spend by practice/model/level, token breakdown, cost trends | Engineering Managers |
| **Tool Usage** | Tool frequency, success rates, accept/reject patterns | Platform / DevOps |
| **User Behavior** | Session depth, peak hours, IDE distribution, top users | Individual Developers |
| **Operational Health** | Error types, latency by model, version distribution | Platform / DevOps |
| **Advanced Analytics** | Cost forecasting, anomaly detection, user clustering | All |

All views share global sidebar filters (date range, practice, level, location, model, IDE/terminal) and handle empty filter states per-chart. Advanced Analytics also uses the active filters: forecasting is fit on the filtered cost history, and anomaly detection / clustering run on filtered session and user subsets.

---

## The API

FastAPI with 20+ endpoints at `http://localhost:8000`. Interactive docs at `/docs`.

```bash
# Examples
curl localhost:8000/api/v1/overview
curl localhost:8000/api/v1/cost/by-practice
curl localhost:8000/api/v1/tools/success-rates
curl "localhost:8000/api/v1/sessions/depth?practice=ML+Engineering&level=L5"
curl localhost:8000/api/v1/data-quality
```

All endpoints support query-parameter filtering. All queries are parameterized (no SQL injection).

---

## Known Limitations & Security

A full security audit is documented in [`docs/known-limitations.md`](docs/known-limitations.md), covering findings by severity (HIGH / MEDIUM / LOW) and what's explicitly not vulnerable.

Key example: the API is implemented as a bonus feature, but the assignment scope doesn't define user authentication — so all routes are public. This is a conscious scope decision, not an oversight. The file documents mitigations for production deployment.

---

## Bonus Features Implemented

All four optional enhancements from the assignment are implemented:

| Enhancement | Implementation |
|------------|----------------|
| **Predictive Analytics** | Cost forecasting (Holt-Winters exponential smoothing) with confidence intervals, session anomaly detection (Isolation Forest) |
| **Advanced Statistical Analysis** | User behavior clustering (K-Means on usage vectors), seniority effect analysis, cost distribution analysis |
| **API Access** | Full FastAPI REST API with 20+ endpoints, query-parameter filtering, Swagger docs |
| **Real-time Capabilities** | Architecture supports incremental ingestion; documented in [SPEC.md](docs/llm-engineering/SPEC.md) |

---

## Data Processing

The ingestion pipeline stream-parses ~500MB of CloudWatch-style nested JSONL:

```
JSONL line → batch → logEvents[] → message (JSON string) → {body, attributes, scope, resource}
```

Key design decisions:
- **NULL-preserving ingestion**: Malformed values become NULL, not 0. Valid zeros stay 0. Imputation happens at the analytics layer, not ingestion. This prevents silent corruption of aggregates.
- **Vectorized bulk insert**: DataFrame-based insert via DuckDB replacement scan, not `executemany`. This reduced ingestion from 248s to ~12s (20x improvement). See [Compound-Engineering.md](docs/llm-engineering/Compound-Engineering.md) for the full story.
- **Data quality tracking**: A `data_quality` table monitors NULL counts and parse failures per field, visible in the Overview dashboard.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `duckdb` | Columnar analytics database |
| `pandas` | DataFrame transforms and bulk insert path |
| `streamlit` | Interactive dashboard |
| `plotly` | Charts (interactive, works with Streamlit) |
| `fastapi` + `uvicorn` | REST API |
| `scikit-learn` | Anomaly detection (Isolation Forest), clustering (K-Means) |
| `statsmodels` | Cost forecasting (Holt-Winters) |
| `pytest` | Testing |
| `httpx` | API test client (FastAPI TestClient) |

No heavyweight frameworks. No Docker. No external databases. One `make setup` and you're running.

---

## Project Structure

```
provectus/
├── Makefile                    # setup, run, test, clean
├── README.md
├── CLAUDE.md                   # project conventions for AI tooling
├── requirements.txt
├── generate_fake_data.py       # deterministic data generator (seed 42)
├── src/
│   ├── ingestion/
│   │   ├── pipeline.py         # JSONL parsing, validation, bulk loading
│   │   └── schema.py           # DuckDB DDL, session materialization
│   ├── analytics/
│   │   └── queries.py          # all analytics queries, return DataFrames
│   ├── dashboard/
│   │   ├── app.py              # Streamlit entrypoint
│   │   ├── filters.py          # global sidebar filters + parameterized WHERE builder
│   │   └── views/              # 6 view modules, each exports render()
│   ├── api/
│   │   └── main.py             # FastAPI with 20+ endpoints
│   └── ml/
│       ├── forecasting.py      # Holt-Winters cost forecasting
│       ├── anomaly.py          # Isolation Forest session anomalies
│       └── clustering.py       # K-Means user clustering
├── tests/
│   ├── test_ingestion.py       # ingestion unit + integration tests
│   ├── test_filters.py         # filter builder unit tests
│   ├── test_api.py             # API endpoint + global filter integration tests
│   └── test_advanced_analytics.py  # Advanced Analytics filter + ML edge-case tests
├── docs/
│   ├── Analytics_Result.pdf         # insights presentation (3-5 slides)
│   ├── known-limitations.md         # security findings by severity
│   ├── llm-engineering/
│   │   ├── SPEC.md                  # full technical specification
│   │   ├── Claude-Code-Sessions-Log.md  # LLM usage log
│   │   └── Compound-Engineering.md      # engineering learnings & pitfalls
│   └── archive/
│       ├── assignment.md            # original assignment (markdown)
│       └── TechnicalAssignment...pdf
└── output/                     # gitignored — regenerated via make setup
    ├── telemetry_logs.jsonl
    ├── employees.csv
    └── analytics.duckdb
```

---

## LLM Usage

This project was built using **Claude Code CLI v2.1.34** (claude-opus-4-6) with **OpenAI Codex** as an external code reviewer.

### Workflow

```
Developer specifies intent + makes architectural decisions
        → Claude Code generates implementation
        → Developer challenges AI decisions, catches issues
        → OpenAI Codex reviews adversarially
        → Developer evaluates findings, questions both AIs
        → Claude Code fixes confirmed issues
        → Repeat (7+ review cycles)
```

The developer independently identified risks (e.g., `safe_int` silently converting malformed data to 0 — corrupting aggregates), challenged AI-generated statistics (*"where is that number coming from?"*), and allowed bidirectional challenge — letting AI push back on decisions too. This was a collaborative engineering process, not copy-paste orchestration.

### What was AI-generated

All Python source code (~22 files, ~3,500 lines), the DuckDB schema, all dashboard views, the REST API, ML models, and 101 tests were generated by Claude Code. The developer made all final architecture decisions, drove UX iterations, caught data integrity bugs, and ran 7+ adversarial review cycles.

### How AI output was validated

1. **Developer critical thinking**: Independently caught silent data corruption (`safe_int` defaulting malformed values to 0), profiled and diagnosed the ingestion bottleneck (248s → 12s), challenged AI-generated statistics, refused non-deterministic estimates
2. **Adversarial code review**: 7+ rounds via OpenAI Codex — caught SQL injection, positional argument bugs, filter semantics errors
3. **Automated tests**: 101 pytest tests (grew from 21 → 41 through review findings → 93 with filter and API coverage → 101 with Advanced Analytics coverage)
4. **Manual dashboard testing**: Every view tested with screenshots
5. **Security audit**: Full-repo review covering all 22 source files

### What the AI missed

Every significant bug was found by the developer or the external reviewer, not by Claude Code:
- Silent data corruption: `safe_int` returning 0 for malformed data, making bad data indistinguishable from real zeros (**caught by developer**)
- Ingestion bottleneck: 248s runtime from row-oriented inserts (**caught by developer** via profiling)
- SQL injection via f-string interpolation — HIGH severity (**caught by reviewer**)
- Positional argument collision in `query()` breaking all analytics (**caught by reviewer**)
- 15+ total bugs across 7+ review cycles
- 0 bugs found proactively by the building AI

The full session analysis with exact quotes, interaction patterns, and behavioral observations is in [`docs/llm-engineering/Claude-Code-Sessions-Log.md`](docs/llm-engineering/Claude-Code-Sessions-Log.md). Engineering pitfalls and their fixes are documented in [`docs/llm-engineering/Compound-Engineering.md`](docs/llm-engineering/Compound-Engineering.md).

---
