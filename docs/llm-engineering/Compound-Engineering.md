# Compound Engineering: Learnings & Pitfalls

Documented issues discovered during development through a multi-agent workflow: Claude Code (builder) + OpenAI Codex (reviewer) + developer (decision-maker). Each section captures what went wrong, how it was caught, and the fix applied.

---

## 1. Ingestion Speed: 248s to 12s (20x Improvement)

### The Problem

The ingestion pipeline took **248 seconds** to process 454,428 telemetry events. Profiling revealed the bottleneck:

| Component | Time | % of Total |
|-----------|------|------------|
| `_flush_buffer()` via `executemany` | 228.6s | 92% |
| `json.loads` | ~6.5s | 2.6% |
| Timestamp parsing (`strptime`) | ~6.1s | 2.5% |
| Session materialization | ~24ms | ~0% |

### Root Cause

`executemany` feeds DuckDB **rows**, not **columns**. This defeats the engine's vectorized, columnar strengths. Every flush also involved Python-side tuple building (`pipeline.py:230`), meaning millions of Python object accesses before DuckDB even started work.

> *"executemany is feeding DuckDB rows, not columns. That defeats the engine's vectorized strengths."* — Developer profiling analysis

### How It Was Caught

The developer profiled the pipeline independently (not the AI) and redirected work from feature development to performance:

> *"nah, we'll do that after we at least a bit optimize the ingestion. I don't have that much time."*

The AI had not flagged the performance issue.

### The Fix

Three changes, in order of impact:

**1. DataFrame bulk insert replacing `executemany` (primary fix)**

Before:
```python
def _flush_buffer(con, table, rows, columns):
    placeholders = ", ".join("?" for _ in columns)
    col_names = ", ".join(columns)
    con.executemany(f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})", rows)
```

After:
```python
def _flush_dataframe(con, table, rows):
    df = pd.DataFrame(rows)
    columns = list(df.columns)
    col_names = ", ".join(columns)
    con.execute(f"INSERT INTO {table} ({col_names}) SELECT * FROM df")
```

DuckDB's replacement scan reads the DataFrame columnar-natively, skipping Python-side row iteration entirely.

**2. Single transaction wrapping**

All inserts wrapped in one transaction to reduce write amplification.

**3. `fromisoformat` over `strptime`**

`datetime.fromisoformat()` is a C-level call; `strptime` does format-string parsing in Python. Small win (~6s to ~2s) but free.

### Result

**248s to ~12s** (20x speedup). The dominant cost shifted from inserts to `json.loads`, which is now the ceiling.

### Takeaway

When working with columnar databases (DuckDB, ClickHouse, BigQuery), always insert data in columnar format. Row-oriented inserts (`executemany`, `INSERT VALUES`) negate the engine's core advantage. Profile before optimizing -- the bottleneck was not where intuition might suggest (not JSON parsing, not timestamp conversion, not session materialization).

---

## 2. SQL Injection via f-string Query Building

### The Problem

The dashboard filter builder and API endpoint filters interpolated user-selected values directly into SQL strings:

```python
# VULNERABLE — values injected directly into SQL
def build_where_clause(filters):
    conditions = []
    for practice in filters["practices"]:
        conditions.append(f"e.practice = '{practice}'")
    return " AND ".join(conditions)
```

This allowed trivial SQL injection. With `practice=["x') OR 1=1 --"]`, the query returned all rows regardless of filters.

### How It Was Caught

An external reviewer (OpenAI Codex) flagged it as **HIGH severity** during the third code review cycle. The AI had written this code and not flagged it across multiple review iterations.

> *"what the hell bro? you trying to get me fired?"* — Developer, upon seeing the finding

### The Fix

All user-facing query paths switched to **parameterized queries** with `?` placeholders:

```python
# SAFE — parameterized
def build_where_clause(filters, timestamp_col="a.timestamp", employee_alias="e",
                       model_col=None, terminal_col=None):
    conditions = []
    params = []

    conditions.append(f"{timestamp_col} >= ?")
    params.append(str(filters['date_start'])[:10])

    for values, col in [
        (filters["practices"], f"{employee_alias}.practice"),
        (filters["levels"], f"{employee_alias}.level"),
    ]:
        if values:
            placeholders = ", ".join("?" for _ in values)
            conditions.append(f"{col} IN ({placeholders})")
            params.extend(values)
        else:
            conditions.append("FALSE")

    return " AND ".join(conditions), params
```

The `query()` function was also updated to accept params as keyword-only:

```python
def query(sql, db_path=DB_PATH, *, params=None):
    con = get_connection(db_path)
    try:
        if params:
            return con.execute(sql, params).df()
        return con.execute(sql).df()
    finally:
        con.close()
```

The `*` separator prevents accidental positional argument collision (which itself was a bug caught in a later review).

Additionally, all query connections use `read_only=True`, adding defense-in-depth even if a theoretical injection occurred.

### Scope of the Fix

- `src/dashboard/filters.py` — `build_where_clause()` returns `(clause, params)` tuple
- `src/api/main.py` — `FilterParams.where()` refactored from f-string to parameterized
- All 6 dashboard views — updated to unpack `(clause, params)` and pass `params=` to `query()`
- `src/analytics/queries.py` — `query()` signature changed to keyword-only `params`

### Takeaway

AI code generators produce SQL injection vulnerabilities naturally. f-string interpolation is the path of least resistance when building dynamic queries, and AI models default to it. In this project, the vulnerability persisted through multiple code generation rounds and was only caught by an external reviewer -- not by the AI, not by the test suite, and not by the developer's manual testing.

The fix pattern for dynamic SQL in Python:
1. Build `WHERE` clauses with `?` placeholders
2. Collect values into a `params` list
3. Return `(clause, params)` as a tuple
4. Pass `params` to the database driver, never interpolate
5. Use `read_only=True` connections as defense-in-depth

---

## 3. Silent Data Corruption: `safe_int` Defaulting Malformed Values to 0

### The Problem

The ingestion pipeline used helper functions `safe_int` and `safe_float` to parse telemetry values. When a value was malformed (e.g., `"abc"` where a number was expected), these functions returned `0` by default:

```python
def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default
```

This made malformed data **indistinguishable from genuine zeros**. A session with `cost_usd = "corrupted"` would be stored as `cost_usd = 0.0` — a valid-looking zero that silently deflates cost aggregates. There's no way to tell whether `0` means "this session was free" or "we couldn't parse the value."

### How It Was Caught

The developer identified this risk while reading the SPEC.md file. The developer questioned the AI's design decision and recognized that defaulting to 0 violated the principle of data integrity:

> *"yes. plan it first though."* — Developer, insisting on a plan before the fix

The developer then drove the entire NULL-preserving ingestion redesign: malformed → NULL, missing → NULL, valid zero → 0. This became a core architectural principle documented in CLAUDE.md.

### The Fix

Changed `safe_int` and `safe_float` defaults from `0`/`0.0` to `None`:

```python
def safe_int(value, default=None, field_key=None):
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        if field_key:
            _parse_failures[field_key] += 1
        return default
```

Added `safe_bool` for boolean fields (`success`), where the same corruption pattern applied — unknown success was being treated as `False`, deflating success rates.

Downstream analytics now use `COALESCE` only where analytically justified, and a `data_quality` table tracks NULL counts and parse failures per field.

### Takeaway

AI-generated code defaults to "make it work" — returning 0 is simpler than propagating NULL and handling it downstream. But in analytics, a silent zero is worse than a visible NULL. The developer's role wasn't just reviewing AI output — it was questioning assumptions that neither AI flagged as problematic.

---

## Meta: The Compound Engineering Pattern

All three issues share a common thread: **AI-generated code follows the path of least resistance**, and the resulting bugs are invisible to the AI itself. The performance bottleneck, the SQL injection, and the silent data corruption were all introduced by Claude Code and never self-corrected.

But the detection wasn't one-dimensional. The developer and the external reviewer caught different classes of bugs:
- **Developer caught**: Silent data corruption (NULL vs 0), ingestion performance bottleneck — both required domain understanding and critical thinking about data integrity
- **External reviewer caught**: SQL injection, positional argument bugs, filter semantics — structural code review findings

The effective mitigation was a **compound engineering workflow** where the developer was an active critical thinker, not a passive intermediary:
1. AI generates code quickly
2. Developer challenges decisions, independently identifies risks
3. External reviewer audits adversarially
4. Developer evaluates findings from both AIs, questions vague conclusions
5. AI fixes confirmed issues
6. Repeat — allowing bidirectional challenge (AI pushes back on developer decisions too)

This loop caught 15+ bugs across 7+ review cycles. Zero bugs were found by the building AI on its own. The developer and reviewer found different but complementary classes of issues.
