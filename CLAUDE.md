# SamCart Analytics Dashboard

## Project
Streamlit multi-page dashboard for SamCart e-commerce analytics. Deployed on Streamlit Community Cloud with daily data sync via GitHub Actions.

## Stack
- Python 3.12, Streamlit, Pandas, Plotly, SQLite (WAL mode), requests
- Auth: streamlit-authenticator
- CI: GitHub Actions daily cron (`sync_job.py`)

## Quality Gates — ALWAYS follow these before completing any task

### 1. Lint with ruff
```bash
ruff check . --fix
```
Fix all issues before committing. Do not suppress warnings without justification.

### 2. Run tests
```bash
pytest tests/ -v
```
All tests must pass. If you add new functionality, add corresponding tests in `tests/`.

### 3. Regression analysis
When modifying `cache.py`, `analytics.py`, or any page file:
- Verify revenue calculations still use charges as source of truth (not orders)
- Verify NULL/empty charge status is treated as successful
- Verify customer_email resolution still works (customers synced first, then ID→email map)
- Verify subscriptions are always full-synced (status is mutable)
- Check that SQL queries use parameterized values (never f-string interpolation with user input)
- Check that table names go through `_validate_table()` whitelist

### 4. Data accuracy checks
After any code change that touches data flow:
- Confirm `_is_successful_charge()` includes NULL/empty status as successful
- Confirm refund statuses are: `refunded`, `partially_refunded`, `refund`
- Confirm incremental sync uses 1-hour overlap window for boundary records
- Confirm `safe_float()` / `safe_int()` handle None, empty string, and "null"
- Spot-check that upsert field mappings in `cache.py` match the API response shapes documented in `methodology.py`

### 5. Security checks
- No raw SQL with user input — always parameterized queries
- Table names validated via `_ALLOWED_TABLES` whitelist
- LIKE queries escape `%`, `_`, `\` wildcards
- No PII in export filenames
- API key never logged or exposed in error messages
- TLS always enabled (`verify=True`)

## Key Architecture Rules
- **API amounts are in cents**: SamCart API returns all monetary values in cents. `cache.py` divides by 100 at the upsert layer so all DB values and downstream analytics are in dollars.
- **Revenue source of truth**: `charges` table, NOT orders. NULL/empty charge status = successful.
- **Customer email**: Resolved via customer_id→email map built from customers table (synced first).
- **Subscriptions**: Always full sync — status is mutable.
- **Products**: Always full sync — small table.
- **Orders/Charges**: Incremental sync with 1-hour overlap + UPSERT.
- **Headless mode**: `cache.sync_all(headless=True)` for CI — prints instead of `st.progress()`.

## File Layout
```
app.py                  — Main dashboard + sync controls
samcart_api.py          — API client (auth, pagination, rate limits)
cache.py                — SQLite cache (schema, sync engine, queries)
analytics.py            — Pure pandas analytics (no DB/API imports)
shared.py               — Singleton cache/client resources
methodology.py          — Methodology docs + API data dictionary
auth.py                 — streamlit-authenticator gate
export.py               — CSV/Excel export with PII stripping
gsheets.py              — Google Sheets export
sync_job.py             — Headless sync for GitHub Actions
pages/                  — Streamlit multi-page files
tests/                  — pytest test suite
.github/workflows/      — GitHub Actions (daily-sync.yml)
```
