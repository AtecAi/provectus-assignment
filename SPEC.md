# Claude Code Usage Analytics Platform — Technical Spec

## 1. Overview

An end-to-end analytics platform that ingests Claude Code telemetry data, stores it in an analytics-optimized database, and presents insights through an interactive dashboard designed for three stakeholder personas.

### Stakeholder Personas

| Persona | Cares about | Primary dashboard pages |
|---------|-------------|------------------------|
| **Engineering Manager** | Cost control, team adoption, cross-team comparisons | Overview, Cost & Tokens |
| **Platform / DevOps** | Errors, latency, version rollout, tool reliability | Operational Health, Tool Usage |
| **Individual Developer** | Personal usage patterns, session efficiency, advanced insights | User Behavior, Advanced Analytics |

## 2. Data Processing

### 2.1 Ingestion Pipeline

**Input:**
- `telemetry_logs.jsonl` — CloudWatch-style JSONL, ~500MB, nested 3 levels deep
- `employees.csv` — 100 employees with practice, level, location

**Parsing challenge:**
```
JSONL line → batch → logEvents[] → message (JSON string) → {body, attributes, scope, resource}
```

Each JSONL line is a batch containing `logEvents`. Each log event's `message` field is a JSON string that must be parsed again to extract the actual event.

**Pipeline steps:**
1. Stream-parse `telemetry_logs.jsonl` line by line (never load full file into memory)
2. For each batch, iterate `logEvents[]`, parse `message` JSON string
3. Flatten nested attributes into typed columns (cast string numbers to float/int)
4. Validate: reject events with missing required fields, log warnings
5. Route each event to its type-specific table based on `body` field
6. Load `employees.csv` into the `employees` table
7. **Post-ingestion:** Run aggregation queries to materialize the `sessions` table

### 2.2 Storage — DuckDB

Column-oriented, zero-config, analytics-optimized. Single file, no server.

**Design decision — no shared `events` table.** Every analytics query targets a specific event type and joins with `employees`. A shared base table would add an extra join to every query with no benefit. Instead, each type-specific table carries the common fields (`timestamp`, `session_id`, `user_email`, etc.) directly. The column duplication is negligible in columnar storage.

**Schema:**

```sql
-- API requests (118K rows)
api_requests (
    event_id              TEXT PRIMARY KEY,   -- from logEvents[].id
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
    cost_usd              DOUBLE,            -- acceptable precision for analytics; not used for billing
    duration_ms           INTEGER
)

-- Tool decisions (151K rows)
tool_decisions (
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
    decision        TEXT NOT NULL,           -- accept | reject
    source          TEXT NOT NULL            -- config | user_temporary | user_permanent | user_reject
)

-- Tool results (148K rows)
tool_results (
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
    result_size_bytes   INTEGER              -- nullable, only present ~30% of the time
)

-- User prompts (35K rows)
user_prompts (
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

-- API errors (1.4K rows)
api_errors (
    event_id    TEXT PRIMARY KEY,
    timestamp   TIMESTAMP NOT NULL,
    session_id  TEXT NOT NULL,
    user_email  TEXT NOT NULL,
    terminal_type TEXT,
    org_id      TEXT,
    scope_version TEXT,
    host_arch   TEXT,
    os_type     TEXT,
    model       TEXT,
    error       TEXT,
    status_code TEXT,                        -- TEXT because some values are "undefined" (non-numeric)
    attempt     INTEGER,
    duration_ms INTEGER
)

-- Employees (100 rows, from CSV)
employees (
    email       TEXT PRIMARY KEY,
    full_name   TEXT,
    practice    TEXT,                        -- Platform Engineering | Data Engineering | ML Engineering | Backend Engineering | Frontend Engineering
    level       TEXT,                        -- L1-L10
    location    TEXT                         -- United States | Germany | United Kingdom | Poland | Canada
)

-- Derived: sessions (5K rows)
-- Materialized post-ingestion via aggregation query across all event tables.
-- Built once after ingestion completes, not a live view.
sessions (
    session_id          TEXT PRIMARY KEY,
    user_email          TEXT NOT NULL,
    start_time          TIMESTAMP,
    end_time            TIMESTAMP,
    duration_sec        INTEGER,
    num_turns           INTEGER,             -- count of user_prompt events
    num_api_calls       INTEGER,
    num_tool_uses       INTEGER,
    total_cost          DOUBLE,
    total_input_tokens  INTEGER,
    total_output_tokens INTEGER,
    error_count         INTEGER
)
```

### 2.3 Field Mapping Notes

- **Email:** Use `attributes.user.email` (the real email). `resource.user.email` is always an empty string — ignore it.
- **Rename:** Raw field `tool_result_size_bytes` maps to column `result_size_bytes` in the `tool_results` table.

### 2.4 Data Validation

- Reject events missing: `timestamp`, `session_id`, `user_email`, or `body` (event type)
- Cast string-typed numbers (`cost_usd`, `duration_ms`, tokens) to proper types; default to 0 on failure
- Log and count rejected/malformed events; print summary at end of ingestion
- Verify all telemetry emails exist in `employees.csv`; flag orphaned events

### 2.5 Testing

- **Unit tests:** Ingestion parsing (nested JSON extraction, type casting, validation logic)
- **Integration test:** Full pipeline — generate small dataset (10 users, 50 sessions), ingest, verify row counts and types in DuckDB

## 3. Analytics & Insights

### Tier 1 — Required (directly asked)

| ID | Insight | Query approach |
|----|---------|---------------|
| A1 | **Token consumption by practice** | SUM input/output/cache tokens from `api_requests` JOIN `employees` GROUP BY practice |
| A2 | **Token consumption by seniority** | Same, GROUP BY level |
| A3 | **Cost by practice and level** | SUM cost_usd GROUP BY practice, level |
| A4 | **Peak usage times** | COUNT `user_prompt` events or distinct sessions by hour-of-day, day-of-week for user activity. Raw event counts overweight long/tool-heavy sessions and should only be used for infrastructure load analysis |
| A5 | **Code generation behaviors** | Tool usage distribution from `tool_decisions` across all 17 tool types (Read, Bash, Edit, Grep, Glob, mcp_tool, Write, TodoWrite, Task, etc.), ranked by frequency |

### Tier 2 — Natural insights from the data

| ID | Insight | What it reveals |
|----|---------|-----------------|
| B1 | **Model preference by practice** | Which teams favor which models (cost vs speed tradeoff) |
| B2 | **Session depth analysis** | Turns per session, tools per turn — who has longer/deeper conversations |
| B3 | **Error patterns over time** | 429 rate limits, error spikes, reliability trends |
| B4 | **Tool rejection rate** | Accept vs reject by tool, by seniority — trust/permission patterns |
| B5 | **Cost efficiency** | Cost per prompt, cost per session — who gets more value per dollar |
| B6 | **IDE/terminal adoption** | VSCode vs PyCharm vs Cursor breakdown across practices |
| B7 | **Version distribution** | Claude Code version spread across users and practices (note: version is fixed per user, not per session — this is a distribution analysis, not a rollout-over-time curve) |
| B8 | **Tool success rates** | Bash fails 7% of the time — which tools are flaky, for whom? |

### Tier 3 — Advanced / ML

| ID | Insight | Approach |
|----|---------|----------|
| C1 | **Cost forecasting** | Time series on daily/weekly cost → Prophet or ARIMA |
| C2 | **Anomaly detection** | Flag sessions with abnormally high cost, error rate, or duration |
| C3 | **User clustering** | K-means on usage vectors (tool mix, cost, session frequency) to identify behavior archetypes |
| C4 | **Seniority effect analysis** | Statistical tests (e.g., Mann-Whitney) comparing L1-L3 vs L7-L10 usage patterns |

## 4. Visualization — Interactive Dashboard

Framework: **Streamlit** (fast to build, Python-native, good for data apps)

### Dashboard pages/tabs:

| Page | Target stakeholder | Content |
|------|--------------------|---------|
| **Overview** | All | KPI cards (total cost, total sessions, active users, error rate), daily activity timeline |
| **Cost & Tokens** | Engineering Manager | Cost by practice, by level, by model. Token breakdown charts. Cost trend over time |
| **Tool Usage** | Platform / DevOps | Tool frequency, success rates, duration. Accept/reject ratios. Filterable by practice/level |
| **User Behavior** | Individual Developer | Session depth, prompt lengths, peak hours heatmap, IDE distribution |
| **Operational Health** | Platform / DevOps | Error rates, 429 trends, latency by model, version adoption |
| **Advanced Analytics** | All | Forecasting charts, anomaly flags, user clusters |

### Filters (global sidebar):
- Date range
- Practice
- Level
- Location
- Model
- Terminal/IDE

## 5. Bonus Features

### 5.1 API Access (FastAPI)
- REST endpoints for all analytics queries
- `/api/v1/cost/by-practice`, `/api/v1/tools/usage`, `/api/v1/sessions/{session_id}`, etc.
- Query parameters for filtering (date range, practice, level)

### 5.2 Predictive Analytics
- Cost forecasting (C1)
- Anomaly detection (C2)
- Exposed in dashboard and API

### 5.3 Real-time Simulation
- A replay script that reads JSONL events in timestamp order and appends them to DuckDB with a configurable speed multiplier
- Dashboard provides a "Live Mode" toggle that periodically re-queries the database and updates charts
- Kept simple — no WebSockets, no Kafka. The point is to demonstrate the concept, not build production streaming infra

### 5.4 Advanced Statistical Analysis
- Seniority effect (C4)
- User clustering (C3)
- Correlation analysis between variables

## 6. Project Setup & Reproducibility

### 6.1 Setup Script

A single `Makefile` that:
1. Creates a Python virtual environment
2. Installs all dependencies from `requirements.txt`
3. Generates the dataset with a **fixed seed** for reproducibility
4. Runs the ingestion pipeline to populate DuckDB
5. Launches the dashboard

```bash
make setup   # steps 1-4
make run     # step 5
make test    # run tests
```

### 6.2 Data Generation (fixed seed)

```bash
python3 generate_fake_data.py --num-users 100 --num-sessions 5000 --days 60 --seed 42
```

Seed 42 is pinned so that:
- Any reviewer generates identical data
- Insights presentation screenshots match the actual data
- Results are fully reproducible

### 6.3 Project Structure

```
provectus/
├── Makefile
├── README.md
├── requirements.txt
├── generate_fake_data.py
├── assignment.md
├── SPEC.md
├── src/
│   ├── ingestion/        # JSONL parsing, validation, DB loading
│   ├── analytics/        # Query functions, aggregations
│   ├── dashboard/        # Streamlit app
│   ├── api/              # FastAPI endpoints
│   └── ml/               # Forecasting, anomaly detection, clustering
├── output/               # .gitignored — generated data
└── tests/
```

## 7. Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| Storage | DuckDB |
| Dashboard | Streamlit |
| API | FastAPI |
| ML | scikit-learn, Prophet/statsmodels |
| Data processing | pandas (for transforms), DuckDB (for queries) |
| Charts | Plotly (interactive, works with Streamlit) |

## 8. Deliverables

### 8.1 README.md
- Project overview (what it is, what it does)
- Architecture diagram or description
- Full setup instructions (prerequisites, install, generate data, run)
- List of all dependencies with brief justification
- LLM usage log (see 8.3)

### 8.2 Insights Presentation (3-5 slides PDF)
- **Slide 1:** Overview — what the platform does, architecture
- **Slide 2:** Key findings — top 3-4 insights from the data (cost by practice, peak hours, tool patterns)
- **Slide 3:** Advanced analytics — forecasting results, anomaly examples, user clusters
- **Slide 4:** Dashboard walkthrough — screenshots of key pages
- **Slide 5:** Technical decisions — why DuckDB, schema design, what worked well

### 8.3 LLM Usage Log
Section in the README covering:
- Which AI tools were used (Claude Code)
- Key prompts and how they shaped the architecture
- How AI-generated output was validated (tests, manual review, iterative refinement)
- What was AI-generated vs manually written
