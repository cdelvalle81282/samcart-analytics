# Scheduled Reports + User Management + Refactoring — Design

**Date**: 2026-04-03
**Status**: Approved

## Overview

Three workstreams:

1. **Scheduled Reports**: Any dashboard report, uploaded to Google Sheets, link delivered to Slack, on a configurable schedule (daily/weekly/monthly)
2. **User Management + Permissions**: Separate auth.db, feature-level permissions, admin UI for CRUD, super admin tier
3. **Codebase Refactoring**: Address findings from deep audit (dead code, duplication, inconsistencies, charge/refund sync conflict)

---

## 1. Scheduled Reports

### Architecture

- **Report Catalog** (`report_catalog.py`): Maps report keys to generator functions. Each generator has signature `generate_X(cache, date_range_days, product_filter) -> pd.DataFrame`. Generators are thin wrappers around existing analytics functions.
- **Report Scheduler** (`report_scheduler.py`): APScheduler `BackgroundScheduler` running as a background thread inside the Streamlit process. On startup, reads active `scheduled_reports` from auth.db and registers CronTrigger jobs. Live updates when reports are added/edited/deleted via admin UI.
- **Delivery**: Report fires → generator produces DataFrame → upload to Google Sheets (per-report worksheet) → post Slack message with sheet link → log to audit table.

### Report Catalog Entries

| Key | Label | Analytics Function |
|-----|-------|--------------------|
| `daily_metrics` | Daily Metrics | `build_daily_summary` |
| `refund_analysis` | Refund Analysis | `refund_analysis` |
| `cohort_performance` | Cohort Performance | `build_cohort_performance` |
| `product_ltv` | Product LTV | `product_ltv_ranking` |
| `subscription_health` | Subscription Health | `churn_analysis` + `trial_conversion_analysis` + `subscription_aging` |
| `customer_segments` | Customer Segments | `rfm_segmentation` + `multi_product_buyers` + `customer_concentration` |
| `product_deep_dive` | Product Deep Dive | `product_mrr_trend` + `product_attach_rates` + `new_vs_renewal_revenue_mix` |
| `revenue_forecast` | Revenue Forecast | `revenue_forecast` |
| `mrr_waterfall` | MRR Waterfall | `mrr_waterfall` |
| `upcoming_renewals` | Upcoming Renewals & Cancellations | `upcoming_renewals_and_cancellations` |
| `vip_customers` | VIP Customers | `vip_customers` |

### Google Sheets Changes

Extend `gsheets.py`:
- `upload_report(df, spreadsheet_id, worksheet_name) -> str` — general-purpose upload, returns sheet URL
- Current `upload_daily_summary` becomes a wrapper calling `upload_report`

### Slack Delivery

New function `send_slack_sheet_link(webhook_url, report_name, sheet_url) -> bool` — posts a clean message with the Google Sheets link. Replaces inline data dumps for scheduled reports.

### Scheduling DB Table

```sql
scheduled_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    report_type     TEXT NOT NULL,       -- key from REPORT_CATALOG
    frequency       TEXT NOT NULL CHECK(frequency IN ('daily','weekly','monthly')),
    day_of_week     INTEGER,             -- 0=Mon for weekly, NULL for daily
    day_of_month    INTEGER,             -- 1-28 for monthly, NULL otherwise
    hour_utc        INTEGER NOT NULL DEFAULT 12,
    product_filter  TEXT,                -- comma-separated product IDs, NULL = all
    date_range_days INTEGER DEFAULT 30,
    spreadsheet_id  TEXT NOT NULL,
    slack_webhook   TEXT NOT NULL,
    slack_channel   TEXT,
    created_by      TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
)
```

### Startup Flow

```
app.py starts → shared.py → init_scheduler()
  reads scheduled_reports from auth.db
  registers APScheduler CronTrigger jobs
  scheduler runs in background thread
```

---

## 2. User Management + Feature-Level Permissions

### Storage

Separate `auth.db` SQLite file (not in samcart_cache.db). Rationale: isolation — analytics DB compromise doesn't leak password hashes.

### Schema

```sql
users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    email         TEXT NOT NULL,
    password_hash TEXT NOT NULL,        -- bcrypt
    role          TEXT NOT NULL DEFAULT 'viewer'
                  CHECK(role IN ('super_admin','admin','viewer')),
    is_active     BOOLEAN NOT NULL DEFAULT 1,
    created_by    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
)

permissions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission_key TEXT NOT NULL,
    granted        BOOLEAN NOT NULL DEFAULT 1,
    UNIQUE(user_id, permission_key)
)
```

### Permission Keys + Role Defaults

| Key | super_admin | admin | viewer |
|-----|:-----------:|:-----:|:------:|
| `page:dashboard` | Y | Y | Y |
| `page:customer_lookup` | Y | Y | Y |
| `page:cohorts` | Y | Y | Y |
| `page:product_ltv` | Y | Y | Y |
| `page:daily_metrics` | Y | Y | Y |
| `page:revenue_forecast` | Y | Y | N |
| `page:refund_analysis` | Y | Y | N |
| `page:subscription_health` | Y | Y | N |
| `page:customer_segments` | Y | Y | N |
| `page:product_deep_dive` | Y | Y | N |
| `feature:export` | Y | Y | N |
| `feature:pii_access` | Y | N | N |
| `feature:sync_data` | Y | Y | N |
| `feature:schedule_reports` | Y | Y | N |
| `admin:manage_users` | Y | Y | N |
| `admin:manage_admins` | Y | N | N |
| `admin:audit_log` | Y | Y | N |

### Admin Hierarchy

- **super_admin**: Can manage all users including other admins. Can promote/demote admins.
- **admin**: Can manage viewers and other admins (cannot create/modify super_admins). Can schedule reports.
- **viewer**: Read-only access to permitted pages. No exports, no sync, no admin features.

### Auth Flow Migration

1. On first run, `auth_db.py` checks if users table is empty
2. If empty, reads users from `secrets.toml` and inserts them with bcrypt hashes
3. Sets a migration flag to avoid re-running
4. `require_auth()` authenticates against auth.db instead of secrets.toml
5. Cookie handling unchanged (streamlit-authenticator)
6. After login, user permissions loaded into `st.session_state["permissions"]`

### New Auth Helpers

```python
require_permission(key: str) -> None    # st.stop() if denied
has_permission(key: str) -> bool         # for conditional UI
```

### Admin UI — Page 13: User Management

Three tabs:

**Tab 1 — Users**: CRUD table. Add User form (username, email, temp password, role). Edit/deactivate/reset password per user. Cannot deactivate self or last super_admin.

**Tab 2 — Permissions**: Select user, see checklist of all permission keys pre-filled from role defaults. Toggle individual overrides. "Reset to defaults" button.

**Tab 3 — Scheduled Reports**: CRUD table for scheduled_reports. Add/edit form with report type, frequency, hour, product filter, sheet ID, webhook URL. "Send Now" test button per report.

Replaces current `12_Report_Settings.py`.

---

## 3. Codebase Refactoring

Findings from deep audit, prioritized:

### High — Correctness

| # | Fix | Location |
|---|-----|----------|
| 1 | Stop writing refund_amount/refund_date in `_upsert_charges` (source is /refunds now) | `cache.py` |
| 2 | Fix `_sync_refunds` inflating total_records count | `cache.py` |
| 3 | Add `fillna`/`strip` to `_is_successful_charge` to match `_is_collected_charge` | `analytics.py` |

### Medium — Dead Code

| # | Fix | Location |
|---|-----|----------|
| 4 | Delete dead `build_cohort_retention` (~60 lines) | `analytics.py` |
| 5 | Delete dead `_ensure_exports_dir` | `export.py` |

### Medium — Duplication

| # | Fix | Location |
|---|-----|----------|
| 6 | Move `load_orders/charges/subscriptions/products()` to `shared.py` | 9 files |
| 7 | Extract `render_doc_tabs(methodology)` to `shared.py` | 10 files |
| 8 | Extract subscription interval-join helper in analytics.py | `analytics.py` |
| 9 | Extract customer net-spend helper in analytics.py | `analytics.py` |
| 10 | Extract `since`-overlap date calculation helper | `cache.py` |
| 11 | Extract `require_admin()` to auth.py | pages 10, 12 |

### Medium — Inconsistencies

| # | Fix | Location |
|---|-----|----------|
| 12 | Canonical `_has_valid_subscription_id()` helper | `analytics.py` |
| 13 | Standardize doc footer pattern (tabs vs expander) | pages 5,7,8,9 |
| 14 | Stop importing private `_to_eastern`, `_is_collected_charge`, `_net_charge_amount` in pages | app.py, page 3 |

### Low — Cleanup

| # | Fix | Location |
|---|-----|----------|
| 15 | Move `import itertools` to module top | `analytics.py` |
| 16 | Rename `get_gsheets_client` to `_get_gsheets_client` | `gsheets.py` |
| 17 | Remove redundant `verify_credentials` call in sync sidebar | `shared.py` |

---

## Future Vision (Not In Scope)

- AI-powered custom report builder: users talk to Claude to create ad-hoc reports
- API connections to external programs
- Rich interactive chart visualizations
