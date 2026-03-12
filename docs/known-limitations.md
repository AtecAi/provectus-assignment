# Known Limitations

Security and operational findings documented during development. This platform is designed for internal analytics use behind a corporate network — not for public-facing deployment without additional hardening.

---

## High Severity

### No API Authentication
**Location:** `src/api/main.py` (all endpoints)

The FastAPI application has no authentication or authorization. All 19 endpoints are publicly accessible to anyone who can reach the port. The `/api/v1/sessions/{session_id}` endpoint returns full session details including `user_email` via `SELECT *`.

**Mitigation for production:** Add API key or OAuth middleware, restrict network access, and replace `SELECT *` with explicit column selection excluding PII where unnecessary.

---

## Medium Severity

### No Dashboard Authentication
**Location:** `src/dashboard/app.py`

The Streamlit dashboard has no authentication. All analytics data — including user emails in the clustering hover tooltip (`advanced_analytics.py:105`) — is visible to anyone who can access port 8501.

### Unpinned Dependency Versions
**Location:** `requirements.txt`

All dependencies use `>=` minimum constraints with no upper bounds or lockfile. A compromised or breaking upstream release would be installed automatically. No `--require-hashes` integrity verification is used during install.

### No API Rate Limiting or Pagination
**Location:** `src/api/main.py`

No rate limiting middleware is configured. Most endpoints return unbounded result sets without `LIMIT` or pagination. Under high concurrency or with large datasets, this could cause resource exhaustion.

### ML Models Retrained on Every Page Load
**Location:** `src/dashboard/views/advanced_analytics.py:26,54,89`

Forecasting, anomaly detection, and clustering models are fit from scratch on every page load with no `@st.cache_data` or `@st.cache_resource`. At the current data scale (~5K sessions) this is fast, but would not scale.

---

## Low Severity

### Exception Details Exposed to Users
**Location:** `src/dashboard/views/advanced_analytics.py:46,81,119`

Python exception messages are rendered directly via `st.warning(f"... unavailable: {e}")`. Depending on the error, this could leak internal file paths or schema details.

### Email Addresses in Logs
**Location:** `src/ingestion/pipeline.py:358`

Orphaned email addresses are logged during ingestion. If logs are shipped to a centralized system, PII could persist in log storage.

### No Connection Pooling
**Location:** `src/analytics/queries.py:9-20`

A new DuckDB connection is opened and closed per query. DuckDB connections are lightweight, but a single dashboard page load triggers 5-10 connection cycles.

### Uvicorn --reload in Makefile
**Location:** `Makefile:26`

The `make api` target runs uvicorn with `--reload`, which is development-only. A production target should omit this flag.

---

## Not Vulnerable

- **SQL Injection** — All user-facing query paths (API and dashboard) use parameterized queries with `?` placeholders. The ingestion pipeline uses f-string SQL only with hardcoded constants.
- **Path Traversal** — No file operations accept user input.
- **Command Injection** — No `subprocess`, `os.system`, `eval`, or `exec` usage.
- **Deserialization** — No `pickle`, `yaml.load`, or `marshal`. ML models are fit fresh, never serialized.
- **SSRF** — No outbound HTTP requests or user-controlled URL fetching.
- **DuckDB read-only** — All query connections use `read_only=True`, preventing data modification even in a theoretical injection scenario.
