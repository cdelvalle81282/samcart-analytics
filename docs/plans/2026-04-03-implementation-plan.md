# Scheduled Reports + User Management + Refactoring — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Clean up the codebase (dead code, duplication, bugs), add a separate auth DB with feature-level permissions and admin UI, build a report catalog with APScheduler-based delivery (Google Sheets + Slack), and add a renewals/cancellations lookahead report.

**Architecture:** Four phases executed sequentially. Phase 1 (refactoring) creates a clean foundation. Phase 2 (auth DB) builds the permission system. Phase 3 (report catalog + scheduler) adds report generation and delivery. Phase 4 (admin UI) ties it all together with a management page.

**Tech Stack:** Python 3.12, Streamlit, SQLite, APScheduler, bcrypt, gspread, requests (Slack webhooks)

**Design doc:** `docs/plans/2026-04-03-scheduled-reports-user-management-design.md`

---

## Phase 1: Codebase Refactoring

### Task 1: Fix `_upsert_charges` refund field clobber

The `/charges` API returns NULL for `refund_amount`/`refund_date`. `_upsert_charges` writes these NULLs, then `_sync_refunds` overwrites with correct data. Remove the refund fields from `_upsert_charges` so they're only written by `_sync_refunds`.

**Files:**
- Modify: `cache.py:297-320` (`_upsert_charges`)
- Modify: `tests/test_cache_migration.py` (update `TestChargeReUpsert` if it tests refund fields from charges API)

**Step 1: Modify `_upsert_charges` to stop writing refund fields**

In `cache.py`, change the INSERT statement in `_upsert_charges` (lines 304-320) to exclude `refund_amount` and `refund_date`:

```python
def _upsert_charges(self, charges: list[dict], customer_map: dict | None = None):
    """INSERT OR REPLACE charges. Refund fields are populated by _sync_refunds."""
    customer_map = customer_map or {}
    for ch in charges:
        customer_id = str(ch.get("customer_id", ""))
        customer_email = customer_map.get(customer_id, "")

        self.conn.execute(
            """INSERT INTO charges
               (id, order_id, subscription_id, customer_email, amount, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   order_id=excluded.order_id,
                   subscription_id=excluded.subscription_id,
                   customer_email=excluded.customer_email,
                   amount=excluded.amount,
                   status=excluded.status,
                   created_at=excluded.created_at""",
            (
                str(ch.get("id", "")),
                str(ch.get("order_id", "") or ""),
                str(ch.get("subscription_rebill_id", "") or ""),
                customer_email,
                safe_float(ch.get("total", ch.get("amount"))) / 100,
                ch.get("charge_refund_status", ch.get("status", "")),
                normalize_ts(ch.get("created_at")),
            ),
        )
```

Key change: switched from `INSERT OR REPLACE` (which overwrites the entire row including refund fields) to `INSERT ... ON CONFLICT DO UPDATE` that only touches non-refund columns. This preserves existing `refund_amount`/`refund_date` values set by `_sync_refunds`.

**Step 2: Update tests that assumed refund fields come from charges API**

Search `tests/` for any test that passes `refund_amount` or `refund_date` in a mock charge dict to `_upsert_charges`. Update those tests to instead use `_sync_refunds` or direct SQL to set refund fields.

**Step 3: Run tests**

Run: `pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add cache.py tests/
git commit -m "fix: stop clobbering refund fields in _upsert_charges

Use INSERT ON CONFLICT DO UPDATE to preserve refund_amount/refund_date
set by _sync_refunds. Previously INSERT OR REPLACE would zero these out
on every full charges sync."
```

---

### Task 2: Fix `_sync_refunds` inflating total_records + `_is_successful_charge` inconsistency

**Files:**
- Modify: `cache.py:453` (`_timed_sync`), and the refunds call in `sync_all`
- Modify: `analytics.py:23-36` (`_is_successful_charge`)

**Step 1: Stop counting refund records in total_records**

In `cache.py` `sync_all`, change the refunds sync call (currently around line 500) from `_timed_sync` to a direct call that doesn't add to `total_records`:

```python
# Refunds: update charges with refund amounts/dates from /refunds endpoint
if headless:
    print("Syncing refunds...")
else:
    progress.progress(0.65, text="Syncing refunds...")
t0 = _time.time()
refund_list = self._sync_refunds(client, headless=headless)
elapsed = _time.time() - t0
if headless:
    print(f"  refunds: {len(refund_list)} records in {elapsed:.1f}s")
```

**Step 2: Fix `_is_successful_charge` to match `_is_collected_charge` pattern**

In `analytics.py`, change `_is_successful_charge` (line 23) from:

```python
def _is_successful_charge(status: pd.Series) -> pd.Series:
    lower = status.str.lower()
    return lower.isin(SUCCESSFUL_CHARGE_STATUSES) | status.isna() | (status == "")
```

To:

```python
def _is_successful_charge(status: pd.Series) -> pd.Series:
    lower = status.fillna("").str.lower().str.strip()
    return lower.isin(SUCCESSFUL_CHARGE_STATUSES) | (lower == "")
```

This matches the `fillna("").str.lower().str.strip()` pattern used by `_is_collected_charge`.

**Step 3: Run tests**

Run: `pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add cache.py analytics.py
git commit -m "fix: stop inflating sync count with refunds, fix _is_successful_charge

Refund sync no longer adds to total_records (they update existing rows,
not new records). _is_successful_charge now uses fillna/strip to match
_is_collected_charge pattern."
```

---

### Task 3: Delete dead code

**Files:**
- Modify: `analytics.py:169-230` (delete `build_cohort_retention`)
- Modify: `export.py:16-17` (delete `_ensure_exports_dir`)

**Step 1: Delete `build_cohort_retention` from analytics.py**

Delete lines 169-230 (the entire function). Verify no imports reference it:

Run: `grep -r "build_cohort_retention" --include="*.py" .`
Expected: Only hits in docs/plans files, not in any live code.

**Step 2: Delete `_ensure_exports_dir` from export.py**

Delete lines 16-17.

**Step 3: Run tests**

Run: `pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add analytics.py export.py
git commit -m "chore: delete dead code

Remove build_cohort_retention (replaced by build_cohort_heatmap) and
_ensure_exports_dir (never called — exports return bytes directly)."
```

---

### Task 4: Extract shared data loaders to `shared.py`

**Files:**
- Modify: `shared.py` (add 4 cached loader functions)
- Modify: `app.py`, `pages/1_Customer_Lookup.py`, `pages/2_Subscription_Cohorts.py`, `pages/3_Product_LTV_Compare.py`, `pages/4_Daily_Metrics.py`, `pages/5_Revenue_Forecasting.py`, `pages/6_Refund_Analysis.py`, `pages/7_Subscription_Health.py`, `pages/8_Customer_Segments.py`, `pages/9_Product_Deep_Dive.py` (replace local loaders with imports)

**Step 1: Add loaders to shared.py**

Append to `shared.py` after `render_sync_sidebar`:

```python
@st.cache_data(ttl=300)
def load_orders():
    return get_cache().get_orders_df()

@st.cache_data(ttl=300)
def load_charges():
    return get_cache().get_charges_df()

@st.cache_data(ttl=300)
def load_subscriptions():
    return get_cache().get_subscriptions_df()

@st.cache_data(ttl=300)
def load_products():
    return get_cache().get_products_df()
```

**Step 2: Add `render_doc_tabs` to shared.py**

```python
def render_doc_tabs(page_methodology: str) -> None:
    """Render the standard How It's Calculated / Available Data Points tabs."""
    from methodology import API_DATA_DICTIONARY
    st.markdown("---")
    doc_tab1, doc_tab2 = st.tabs(["How It's Calculated", "Available Data Points"])
    with doc_tab1:
        st.markdown(page_methodology)
    with doc_tab2:
        st.markdown(API_DATA_DICTIONARY)
```

**Step 3: Update each page file**

For each of the 10 files listed above:
1. Remove the local `load_orders`, `load_charges`, `load_subscriptions`, `load_products` function definitions
2. Add them to the existing `from shared import ...` line
3. Replace the doc tabs block with `render_doc_tabs(PAGE_METHODOLOGY)` call
4. For pages 5, 7, 8, 9: change from `st.expander` pattern to `render_doc_tabs` (standardizes UX)

**Step 4: Fix private function leaks**

In `analytics.py`, add a public wrapper:

```python
def total_net_revenue(charges_df: pd.DataFrame, orders_df: pd.DataFrame) -> float:
    """Calculate total net realized revenue from charges, falling back to orders."""
    if not charges_df.empty:
        collected = charges_df[_is_collected_charge(charges_df["status"])].copy()
        if not collected.empty:
            collected["net_amount"] = _net_charge_amount(collected)
            return collected["net_amount"].sum()
    return orders_df["total"].sum() if not orders_df.empty else 0.0
```

Update `app.py` to use `from analytics import total_net_revenue` instead of importing `_is_collected_charge` and `_net_charge_amount`.

For `pages/3_Product_LTV_Compare.py`, move the `_to_eastern` call into `product_ltv_ranking` itself (or make it public as `to_eastern`).

**Step 5: Run tests**

Run: `pytest tests/ -v`
Expected: All pass

**Step 6: Lint**

Run: `ruff check .`
Expected: Clean (no unused imports)

**Step 7: Commit**

```bash
git add shared.py app.py analytics.py pages/
git commit -m "refactor: extract shared loaders, doc tabs, fix private imports

Move load_orders/charges/subscriptions/products to shared.py.
Add render_doc_tabs() for consistent methodology display.
Add total_net_revenue() public API, stop importing private functions.
Standardize all pages to use st.tabs for doc sections."
```

---

### Task 5: Extract duplicated helpers in analytics.py

**Files:**
- Modify: `analytics.py`

**Step 1: Extract `_has_valid_subscription_id` helper**

Add near the top of `analytics.py` (after the status helpers):

```python
def _has_valid_subscription_id(series: pd.Series) -> pd.Series:
    """Return boolean mask for rows with a valid (non-empty, non-NaN) subscription_id."""
    cleaned = series.fillna("").astype(str).str.strip()
    return (cleaned != "") & (cleaned != "nan") & (cleaned != "None")
```

Replace all 4 subscription ID cleaning sites (lines ~276-278, ~452-454, ~781, ~965) with this helper.

**Step 2: Extract `_join_subscription_interval` helper**

```python
def _join_subscription_interval(df: pd.DataFrame, subscriptions_df: pd.DataFrame) -> pd.DataFrame:
    """Join subscription interval onto a charges DataFrame."""
    if (
        not subscriptions_df.empty
        and "id" in subscriptions_df.columns
        and "interval" in subscriptions_df.columns
    ):
        interval_map = (
            subscriptions_df[["id", "interval"]]
            .drop_duplicates("id", keep="last")
            .rename(columns={"id": "subscription_id"})
        )
        interval_map["subscription_id"] = interval_map["subscription_id"].astype(str)
        df["subscription_id"] = df["subscription_id"].astype(str)
        df = df.merge(interval_map, on="subscription_id", how="left", suffixes=("", "_sub"))
        if "interval_sub" in df.columns:
            df["interval"] = df["interval_sub"].fillna(df.get("interval", pd.NA))
            df = df.drop(columns=["interval_sub"])
    else:
        if "interval" not in df.columns:
            df["interval"] = pd.NA
    return df
```

Replace the duplicated blocks in `build_cohort_performance` and `build_cohort_heatmap`.

**Step 3: Extract `_customer_net_spend` helper**

```python
def _customer_net_spend(charges_df: pd.DataFrame, orders_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate per-customer net spend. Returns DataFrame with [customer_email, total_spend]."""
    if not charges_df.empty:
        valid = charges_df[_is_collected_charge(charges_df["status"])].copy()
        if not valid.empty:
            valid["net_amount"] = _net_charge_amount(valid)
            return (
                valid.groupby("customer_email")["net_amount"]
                .sum().reset_index()
                .rename(columns={"net_amount": "total_spend"})
            )
    return (
        orders_df.groupby("customer_email")["total"]
        .sum().reset_index()
        .rename(columns={"total": "total_spend"})
    )
```

Replace the duplicated blocks in `calculate_customer_ltv` and `new_customer_ltv_by_entry_product`.

**Step 4: Move `import itertools` to module top**

Move the `import itertools` from line ~1752 (inside `multi_product_buyers`) to the top-level import block.

**Step 5: Run tests**

Run: `pytest tests/ -v`
Expected: All pass

**Step 6: Commit**

```bash
git add analytics.py
git commit -m "refactor: extract shared helpers in analytics.py

Add _has_valid_subscription_id, _join_subscription_interval,
_customer_net_spend helpers. Eliminates 4 duplicated patterns.
Move itertools import to module top."
```

---

### Task 6: Minor cleanups in cache.py, shared.py, gsheets.py

**Files:**
- Modify: `cache.py` (extract `_incremental_since` helper)
- Modify: `shared.py` (remove redundant `verify_credentials` call)
- Modify: `gsheets.py` (rename `get_gsheets_client` to `_get_gsheets_client`)

**Step 1: Extract `_incremental_since` in cache.py**

Add method to `SamCartCache`:

```python
def _incremental_since(self, table_name: str) -> str | None:
    """Calculate the since timestamp with 1-hour overlap for incremental sync."""
    last_sync = self.get_last_sync(table_name)
    if last_sync:
        dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
        return (dt - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return None
```

Replace the two duplicated 5-line blocks in `sync_all` (customers and orders) with:

```python
since = None if force_full else self._incremental_since("customers")
```

**Step 2: Remove redundant `verify_credentials` in shared.py**

In `render_sync_sidebar`, the sync button handler (line 63) calls `client.verify_credentials()` a second time. Remove this redundant call — the sidebar already shows connection status above. Change the sync button handler to just call `cache.sync_all` directly.

**Step 3: Rename `get_gsheets_client` to `_get_gsheets_client` in gsheets.py**

It's only called internally by `upload_daily_summary`.

**Step 4: Run tests and lint**

Run: `pytest tests/ -v && ruff check .`
Expected: All pass, all clean

**Step 5: Commit**

```bash
git add cache.py shared.py gsheets.py
git commit -m "refactor: extract _incremental_since, remove redundant verify, rename private helper"
```

---

## Phase 2: Auth Database + Permission System

### Task 7: Create `auth_db.py` with schema and CRUD

**Files:**
- Create: `auth_db.py`
- Test: `tests/test_auth_db.py`

**Step 1: Write tests for AuthDB**

Create `tests/test_auth_db.py`:

```python
import os
import pytest
from auth_db import AuthDB

@pytest.fixture
def db(tmp_path):
    return AuthDB(str(tmp_path / "test_auth.db"))

class TestUserCRUD:
    def test_create_user(self, db):
        user = db.create_user("alice", "alice@test.com", "password123", "viewer", created_by="admin")
        assert user["username"] == "alice"
        assert user["role"] == "viewer"

    def test_create_duplicate_username_fails(self, db):
        db.create_user("alice", "a@test.com", "pass", "viewer")
        with pytest.raises(ValueError, match="already exists"):
            db.create_user("alice", "b@test.com", "pass", "viewer")

    def test_authenticate_valid(self, db):
        db.create_user("alice", "a@test.com", "secret", "viewer")
        user = db.authenticate("alice", "secret")
        assert user is not None
        assert user["username"] == "alice"

    def test_authenticate_wrong_password(self, db):
        db.create_user("alice", "a@test.com", "secret", "viewer")
        assert db.authenticate("alice", "wrong") is None

    def test_authenticate_inactive_user(self, db):
        db.create_user("alice", "a@test.com", "secret", "viewer")
        db.deactivate_user("alice")
        assert db.authenticate("alice", "secret") is None

    def test_list_users(self, db):
        db.create_user("alice", "a@test.com", "p", "viewer")
        db.create_user("bob", "b@test.com", "p", "admin")
        users = db.list_users()
        assert len(users) == 2

    def test_update_role(self, db):
        db.create_user("alice", "a@test.com", "p", "viewer")
        db.update_user("alice", role="admin")
        user = db.get_user("alice")
        assert user["role"] == "admin"

    def test_cannot_deactivate_last_super_admin(self, db):
        db.create_user("boss", "b@test.com", "p", "super_admin")
        with pytest.raises(ValueError, match="last super_admin"):
            db.deactivate_user("boss")

class TestPermissions:
    def test_default_permissions_for_role(self, db):
        db.create_user("alice", "a@test.com", "p", "viewer")
        perms = db.get_permissions("alice")
        assert "page:dashboard" in perms
        assert "admin:manage_users" not in perms

    def test_grant_permission(self, db):
        db.create_user("alice", "a@test.com", "p", "viewer")
        db.set_permission("alice", "feature:export", True)
        perms = db.get_permissions("alice")
        assert "feature:export" in perms

    def test_revoke_permission(self, db):
        db.create_user("alice", "a@test.com", "p", "admin")
        db.set_permission("alice", "feature:export", False)
        perms = db.get_permissions("alice")
        assert "feature:export" not in perms

    def test_reset_to_defaults(self, db):
        db.create_user("alice", "a@test.com", "p", "admin")
        db.set_permission("alice", "feature:export", False)
        db.reset_permissions_to_defaults("alice")
        perms = db.get_permissions("alice")
        assert "feature:export" in perms

class TestScheduledReports:
    def test_create_report(self, db):
        r = db.create_scheduled_report(
            name="Daily Sales", report_type="daily_metrics",
            frequency="daily", hour_utc=12,
            spreadsheet_id="abc123", slack_webhook="https://hooks.slack.com/xxx",
            created_by="admin",
        )
        assert r["name"] == "Daily Sales"
        assert r["is_active"] == 1

    def test_list_active_reports(self, db):
        db.create_scheduled_report(
            name="R1", report_type="daily_metrics", frequency="daily",
            hour_utc=12, spreadsheet_id="s1", slack_webhook="w1", created_by="admin",
        )
        reports = db.list_scheduled_reports(active_only=True)
        assert len(reports) == 1

    def test_deactivate_report(self, db):
        r = db.create_scheduled_report(
            name="R1", report_type="daily_metrics", frequency="daily",
            hour_utc=12, spreadsheet_id="s1", slack_webhook="w1", created_by="admin",
        )
        db.deactivate_scheduled_report(r["id"])
        reports = db.list_scheduled_reports(active_only=True)
        assert len(reports) == 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_auth_db.py -v`
Expected: ImportError — `auth_db` doesn't exist yet

**Step 3: Implement `auth_db.py`**

Create `auth_db.py` with:
- `AuthDB` class (takes `db_path` param, defaults to `auth.db`)
- Schema creation in `__init__`
- `ROLE_DEFAULTS` dict mapping roles to their default permission keys
- All CRUD methods: `create_user`, `get_user`, `list_users`, `update_user`, `deactivate_user`, `reactivate_user`, `reset_password`, `authenticate` (bcrypt verify)
- Permission methods: `get_permissions` (returns set of granted keys — merges role defaults with overrides), `set_permission`, `reset_permissions_to_defaults`
- Scheduled report methods: `create_scheduled_report`, `list_scheduled_reports`, `get_scheduled_report`, `update_scheduled_report`, `deactivate_scheduled_report`
- Security: `chmod 600` on db file, bcrypt for passwords, parameterized queries

**Step 4: Run tests**

Run: `pytest tests/test_auth_db.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add auth_db.py tests/test_auth_db.py
git commit -m "feat: add auth_db.py with users, permissions, scheduled reports

Separate auth.db SQLite file for user management.
Feature-level permissions with role defaults (super_admin/admin/viewer).
Scheduled reports table for report configuration storage."
```

---

### Task 8: Migrate `auth.py` to use auth_db

**Files:**
- Modify: `auth.py`
- Test: `tests/test_auth_migration.py`

**Step 1: Write migration test**

Test that `require_auth` works with DB-backed users after migrating from secrets.toml.

**Step 2: Update `auth.py`**

- Add `get_auth_db()` singleton (like `get_cache()`)
- `require_auth()`: check if auth.db has users; if not, migrate from secrets.toml
- After auth, load permissions into `st.session_state["permissions"]`
- Add `require_permission(key)` and `has_permission(key)` helpers
- Keep `is_admin()` and `get_user_role()` working but source from DB
- `require_admin()` helper for admin pages (replaces duplicated gate in pages 10, 12)

**Step 3: Update pages 10 and 12 to use `require_admin()`**

Replace the 3-line admin gate blocks with `require_admin()`.

**Step 4: Run tests**

Run: `pytest tests/ -v`
Expected: All pass

**Step 5: Commit**

```bash
git add auth.py auth_db.py pages/10_Audit_Log.py pages/12_Report_Settings.py tests/
git commit -m "feat: migrate auth.py to use auth_db

Auto-migrates users from secrets.toml on first run.
Loads permissions into session state after login.
Add require_permission(), has_permission(), require_admin() helpers."
```

---

### Task 9: Add permission checks to all pages

**Files:**
- Modify: All page files in `pages/`
- Modify: `app.py`

**Step 1: Add `require_permission` calls to each page**

After `require_auth()` in each page, add the appropriate permission check:

```python
# pages/1_Customer_Lookup.py
require_permission("page:customer_lookup")

# pages/4_Daily_Metrics.py
require_permission("page:daily_metrics")
# ... etc for all pages
```

**Step 2: Wrap feature-level UI elements**

```python
# Export buttons — wrap with has_permission check
if has_permission("feature:export"):
    st.download_button(...)

# Sync button in shared.py — check feature:sync_data
if has_permission("feature:sync_data"):
    sync_btn = st.sidebar.button("Sync Data", ...)
```

**Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add app.py pages/ shared.py
git commit -m "feat: add permission checks to all pages and features

Each page checks its page:* permission on load.
Export buttons gated by feature:export.
Sync controls gated by feature:sync_data."
```

---

## Phase 3: Report Catalog + Scheduler

### Task 10: Build the renewals lookahead report

**Files:**
- Modify: `analytics.py` (add `upcoming_renewals_and_cancellations`)
- Test: `tests/test_renewals_report.py`

**Step 1: Write tests**

```python
import pandas as pd
import pytest
from datetime import datetime, timedelta, timezone

from analytics import upcoming_renewals_and_cancellations

def _make_subs(rows):
    """Helper to build a subscriptions DataFrame."""
    return pd.DataFrame(rows)

class TestUpcomingRenewals:
    def test_renewal_within_window(self):
        now = datetime.now(timezone.utc)
        subs = _make_subs([{
            "id": "1", "customer_email": "a@test.com",
            "product_name": "Course A", "status": "active",
            "next_bill_date": (now + timedelta(days=5)).isoformat(),
            "interval": "monthly", "price": 49.99,
        }])
        result = upcoming_renewals_and_cancellations(subs, lookahead_weeks=1)
        assert len(result["renewals"]) == 1
        assert result["renewals"].iloc[0]["customer_email"] == "a@test.com"

    def test_renewal_outside_window(self):
        now = datetime.now(timezone.utc)
        subs = _make_subs([{
            "id": "1", "customer_email": "a@test.com",
            "product_name": "Course A", "status": "active",
            "next_bill_date": (now + timedelta(days=30)).isoformat(),
            "interval": "monthly", "price": 49.99,
        }])
        result = upcoming_renewals_and_cancellations(subs, lookahead_weeks=1)
        assert len(result["renewals"]) == 0

    def test_cancellation_within_window(self):
        now = datetime.now(timezone.utc)
        subs = _make_subs([{
            "id": "2", "customer_email": "b@test.com",
            "product_name": "Course B", "status": "canceled",
            "canceled_at": (now + timedelta(days=5)).isoformat(),
            "next_bill_date": None, "interval": "monthly", "price": 29.99,
        }])
        result = upcoming_renewals_and_cancellations(subs, lookahead_weeks=1)
        assert len(result["cancellations"]) == 1

    def test_multiple_lookahead_windows(self):
        now = datetime.now(timezone.utc)
        subs = _make_subs([
            {"id": "1", "customer_email": "a@test.com", "product_name": "P1",
             "status": "active", "next_bill_date": (now + timedelta(days=5)).isoformat(),
             "interval": "monthly", "price": 49.99},
            {"id": "2", "customer_email": "b@test.com", "product_name": "P2",
             "status": "active", "next_bill_date": (now + timedelta(days=20)).isoformat(),
             "interval": "monthly", "price": 29.99},
        ])
        r1 = upcoming_renewals_and_cancellations(subs, lookahead_weeks=1)
        r4 = upcoming_renewals_and_cancellations(subs, lookahead_weeks=4)
        assert len(r1["renewals"]) == 1
        assert len(r4["renewals"]) == 2
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_renewals_report.py -v`
Expected: ImportError

**Step 3: Implement `upcoming_renewals_and_cancellations`**

Add to `analytics.py`:

```python
def upcoming_renewals_and_cancellations(
    subscriptions_df: pd.DataFrame,
    lookahead_weeks: int = 1,
    product_filter: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Find subscriptions due for renewal or set to cancel within the lookahead window.

    Returns dict with 'renewals' and 'cancellations' DataFrames.
    Columns: customer_email, product_name, interval, price, next_bill_date/canceled_at, days_until
    """
    if subscriptions_df.empty:
        empty = pd.DataFrame()
        return {"renewals": empty, "cancellations": empty}

    subs = subscriptions_df.copy()
    now = pd.Timestamp.now(tz="UTC")
    cutoff = now + pd.Timedelta(weeks=lookahead_weeks)

    if product_filter:
        subs = subs[subs["product_name"].isin(product_filter)]

    # --- Upcoming renewals: active subs with next_bill_date in window ---
    renewals = pd.DataFrame()
    if "next_bill_date" in subs.columns:
        active = subs[subs["status"].str.lower() == "active"].copy()
        active["next_bill_date"] = pd.to_datetime(active["next_bill_date"], utc=True, errors="coerce")
        active = active.dropna(subset=["next_bill_date"])
        upcoming = active[(active["next_bill_date"] >= now) & (active["next_bill_date"] <= cutoff)].copy()
        if not upcoming.empty:
            upcoming["days_until"] = (upcoming["next_bill_date"] - now).dt.days
            renewals = upcoming[["customer_email", "product_name", "interval", "price",
                                 "next_bill_date", "days_until"]].sort_values("days_until")

    # --- Upcoming cancellations: canceled subs with canceled_at in future window ---
    cancellations = pd.DataFrame()
    if "canceled_at" in subs.columns:
        canceled = subs[subs["status"].str.lower().isin(["canceled", "cancelled"])].copy()
        canceled["canceled_at"] = pd.to_datetime(canceled["canceled_at"], utc=True, errors="coerce")
        canceled = canceled.dropna(subset=["canceled_at"])
        upcoming_cancel = canceled[
            (canceled["canceled_at"] >= now) & (canceled["canceled_at"] <= cutoff)
        ].copy()
        if not upcoming_cancel.empty:
            upcoming_cancel["days_until"] = (upcoming_cancel["canceled_at"] - now).dt.days
            cancellations = upcoming_cancel[["customer_email", "product_name", "interval", "price",
                                             "canceled_at", "days_until"]].sort_values("days_until")

    return {"renewals": renewals, "cancellations": cancellations}
```

**Step 4: Run tests**

Run: `pytest tests/test_renewals_report.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add analytics.py tests/test_renewals_report.py
git commit -m "feat: add upcoming renewals and cancellations report

Shows subscriptions due for renewal or cancellation within a
configurable lookahead window (1/2/4 weeks). Supports product filter."
```

---

### Task 10b: Build VIP customers report

**Files:**
- Modify: `analytics.py` (add `vip_customers`)
- Test: `tests/test_vip_customers.py`

**Step 1: Write tests**

```python
import pandas as pd
import pytest
from analytics import vip_customers

class TestVIPCustomers:
    def test_high_ltv_above_threshold(self):
        charges = pd.DataFrame([
            {"customer_email": "whale@test.com", "amount": 5000, "status": None, "refund_amount": 0},
            {"customer_email": "small@test.com", "amount": 100, "status": None, "refund_amount": 0},
        ])
        orders = pd.DataFrame(columns=["customer_email", "total"])
        subs = pd.DataFrame(columns=["customer_email", "status", "interval", "billing_cycle_count", "product_name"])
        result = vip_customers(charges, orders, subs, ltv_threshold=4000)
        assert len(result["high_ltv"]) == 1
        assert result["high_ltv"].iloc[0]["customer_email"] == "whale@test.com"

    def test_loyal_subscribers(self):
        charges = pd.DataFrame(columns=["customer_email", "amount", "status", "refund_amount"])
        orders = pd.DataFrame(columns=["customer_email", "total"])
        subs = pd.DataFrame([
            {"customer_email": "loyal@test.com", "status": "active", "interval": "monthly",
             "billing_cycle_count": 6, "product_name": "Course A", "price": 49.99},
            {"customer_email": "new@test.com", "status": "active", "interval": "monthly",
             "billing_cycle_count": 1, "product_name": "Course A", "price": 49.99},
        ])
        result = vip_customers(charges, orders, subs, min_billing_cycles=3)
        assert len(result["loyal_subscribers"]) == 1
        assert result["loyal_subscribers"].iloc[0]["customer_email"] == "loyal@test.com"

    def test_custom_thresholds(self):
        charges = pd.DataFrame([
            {"customer_email": "a@test.com", "amount": 1500, "status": None, "refund_amount": 0},
        ])
        orders = pd.DataFrame(columns=["customer_email", "total"])
        subs = pd.DataFrame(columns=["customer_email", "status", "interval", "billing_cycle_count", "product_name"])
        # Default threshold $4000 — should not appear
        r1 = vip_customers(charges, orders, subs, ltv_threshold=4000)
        assert len(r1["high_ltv"]) == 0
        # Lower threshold — should appear
        r2 = vip_customers(charges, orders, subs, ltv_threshold=1000)
        assert len(r2["high_ltv"]) == 1
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_vip_customers.py -v`
Expected: ImportError

**Step 3: Implement `vip_customers`**

Add to `analytics.py`:

```python
def vip_customers(
    charges_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    subscriptions_df: pd.DataFrame,
    ltv_threshold: float = 4000.0,
    min_billing_cycles: int = 3,
    product_filter: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Identify VIP customers by high LTV or subscription loyalty.

    Returns dict with:
    - 'high_ltv': customers with net lifetime spend >= ltv_threshold
    - 'loyal_subscribers': active monthly subscribers with >= min_billing_cycles
    """
    # --- High LTV ---
    spend = _customer_net_spend(charges_df, orders_df)
    high_ltv = spend[spend["total_spend"] >= ltv_threshold].copy()
    high_ltv = high_ltv.sort_values("total_spend", ascending=False)

    # --- Loyal subscribers ---
    loyal = pd.DataFrame()
    if not subscriptions_df.empty:
        subs = subscriptions_df.copy()
        active = subs[subs["status"].str.lower() == "active"]
        if product_filter:
            active = active[active["product_name"].isin(product_filter)]
        if "billing_cycle_count" in active.columns:
            loyal = active[active["billing_cycle_count"] >= min_billing_cycles].copy()
            loyal = loyal[["customer_email", "product_name", "interval", "price",
                           "billing_cycle_count"]].sort_values("billing_cycle_count", ascending=False)

    return {"high_ltv": high_ltv, "loyal_subscribers": loyal}
```

**Step 4: Run tests**

Run: `pytest tests/test_vip_customers.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add analytics.py tests/test_vip_customers.py
git commit -m "feat: add VIP customers report

Identifies high-LTV customers (default >= $4000) and loyal subscribers
(active with configurable minimum billing cycles). Both thresholds are
adjustable per report configuration."
```

---

### Task 11: Build report catalog

**Files:**
- Create: `report_catalog.py`
- Test: `tests/test_report_catalog.py`

**Step 1: Write tests**

Test that every catalog entry has a callable generator that returns a DataFrame.

**Step 2: Implement `report_catalog.py`**

Define `REPORT_CATALOG` dict. Each generator function loads data from cache and calls existing analytics functions. Include the new `upcoming_renewals` report type.

Generators must all follow signature: `generate_X(cache, date_range_days=30, product_filter=None) -> pd.DataFrame`

Include the two new report types:
- `upcoming_renewals`: uses `upcoming_renewals_and_cancellations` — configurable lookahead (1/2/4 weeks)
- `vip_customers`: uses `vip_customers` — configurable LTV threshold and min billing cycles

For multi-DataFrame reports (like renewals returning dict, or subscription_health returning churn + trial + aging), flatten into a single DataFrame or return a dict of DataFrames that the upload function can handle as multiple worksheets.

**Step 3: Run tests**

Run: `pytest tests/test_report_catalog.py -v`
Expected: All pass

**Step 4: Commit**

```bash
git add report_catalog.py tests/test_report_catalog.py
git commit -m "feat: add report catalog with generators for all dashboard reports

Maps report keys to generator functions. Includes daily_metrics,
refund_analysis, cohort_performance, product_ltv, subscription_health,
customer_segments, product_deep_dive, revenue_forecast, mrr_waterfall,
and upcoming_renewals."
```

---

### Task 12: Extend gsheets.py and add Slack link delivery

**Files:**
- Modify: `gsheets.py` (generalize upload, return URL)
- Modify: `notifications.py` (add `send_slack_sheet_link`)
- Test: `tests/test_report_delivery.py`

**Step 1: Write tests**

Test `upload_report` returns a URL string. Test `send_slack_sheet_link` posts correctly (mock requests).

**Step 2: Generalize gsheets.py**

- Rename `get_gsheets_client` to `_get_gsheets_client` (from Task 6 if not already done)
- Add `upload_report(df, spreadsheet_id, worksheet_name) -> str` that returns the sheet URL
- Keep `upload_daily_summary` as a wrapper

**Step 3: Add `send_slack_sheet_link` to notifications.py**

```python
def send_slack_sheet_link(webhook_url: str, report_name: str, sheet_url: str) -> bool:
    """Post a Google Sheets link to Slack via incoming webhook."""
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Report: {report_name}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"<{sheet_url}|Open in Google Sheets>"}},
    ]
    try:
        resp = requests.post(webhook_url, json={"blocks": blocks}, timeout=10)
        resp.raise_for_status()
        return True
    except Exception:
        logger.exception("Failed to send Slack sheet link: %s", report_name)
        return False
```

**Step 4: Run tests**

Run: `pytest tests/test_report_delivery.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add gsheets.py notifications.py tests/test_report_delivery.py
git commit -m "feat: generalize gsheets upload, add Slack sheet link delivery

upload_report() returns sheet URL. send_slack_sheet_link() posts
Google Sheets link to Slack channel via webhook."
```

---

### Task 13: Build report scheduler

**Files:**
- Create: `report_scheduler.py`
- Modify: `shared.py` (start scheduler on app boot)
- Test: `tests/test_report_scheduler.py`

**Step 1: Write tests**

Test that `ReportScheduler` registers/removes jobs, and that `_execute_report` calls the catalog generator → gsheets upload → Slack delivery chain.

**Step 2: Implement `report_scheduler.py`**

```python
"""APScheduler-based report scheduler — runs as background thread in Streamlit."""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from auth_db import AuthDB
from report_catalog import REPORT_CATALOG, generate_report
from gsheets import upload_report
from notifications import send_slack_sheet_link
from cache import SamCartCache

logger = logging.getLogger(__name__)

class ReportScheduler:
    def __init__(self, auth_db: AuthDB, cache: SamCartCache):
        self.auth_db = auth_db
        self.cache = cache
        self.scheduler = BackgroundScheduler()

    def start(self):
        """Load all active reports from DB and start the scheduler."""
        reports = self.auth_db.list_scheduled_reports(active_only=True)
        for report in reports:
            self._add_job(report)
        self.scheduler.start()

    def _add_job(self, report: dict):
        """Register an APScheduler job for a scheduled report."""
        trigger = self._build_trigger(report)
        self.scheduler.add_job(
            self._execute_report,
            trigger=trigger,
            args=[report["id"]],
            id=f"report_{report['id']}",
            replace_existing=True,
        )

    def _build_trigger(self, report: dict) -> CronTrigger:
        """Build a CronTrigger from report config."""
        kwargs = {"hour": report["hour_utc"]}
        if report["frequency"] == "weekly":
            kwargs["day_of_week"] = report.get("day_of_week", 0)
        elif report["frequency"] == "monthly":
            kwargs["day"] = report.get("day_of_month", 1)
        return CronTrigger(**kwargs)

    def _execute_report(self, report_id: int):
        """Run a single report: generate → upload → notify."""
        report = self.auth_db.get_scheduled_report(report_id)
        if not report or not report["is_active"]:
            return

        catalog_entry = REPORT_CATALOG.get(report["report_type"])
        if not catalog_entry:
            logger.error("Unknown report type: %s", report["report_type"])
            return

        product_filter = report["product_filter"].split(",") if report.get("product_filter") else None

        try:
            df = generate_report(
                report["report_type"], self.cache,
                date_range_days=report.get("date_range_days", 30),
                product_filter=product_filter,
            )
            sheet_url = upload_report(df, report["spreadsheet_id"], report["name"])
            send_slack_sheet_link(report["slack_webhook"], report["name"], sheet_url)
            logger.info("Report delivered: %s", report["name"])
        except Exception:
            logger.exception("Failed to execute report: %s", report["name"])

    def reload_report(self, report_id: int):
        """Reload a single report job (called after admin edits)."""
        job_id = f"report_{report_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
        report = self.auth_db.get_scheduled_report(report_id)
        if report and report["is_active"]:
            self._add_job(report)

    def remove_report(self, report_id: int):
        """Remove a report job."""
        job_id = f"report_{report_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

    def run_now(self, report_id: int):
        """Immediately execute a report (for test/preview)."""
        self._execute_report(report_id)
```

**Step 3: Wire into shared.py**

```python
@st.cache_resource
def get_scheduler() -> ReportScheduler:
    from report_scheduler import ReportScheduler
    scheduler = ReportScheduler(get_auth_db(), get_cache())
    scheduler.start()
    return scheduler
```

**Step 4: Add `apscheduler` to requirements**

Add `apscheduler>=3.10` to `requirements.txt`.

**Step 5: Run tests**

Run: `pytest tests/test_report_scheduler.py -v`
Expected: All pass

**Step 6: Commit**

```bash
git add report_scheduler.py shared.py tests/test_report_scheduler.py requirements.txt
git commit -m "feat: add APScheduler-based report scheduler

Background thread runs scheduled reports: generate DataFrame,
upload to Google Sheets, post link to Slack. Supports live
reload when admin adds/edits/removes reports."
```

---

## Phase 4: Admin UI

### Task 14: Build User Management page

**Files:**
- Create: `pages/13_User_Management.py`
- Remove: `pages/12_Report_Settings.py` (replaced by tab 3 in new page)

**Step 1: Implement page with three tabs**

**Tab 1 — Users:**
- `st.dataframe` showing all users
- "Add User" form in `st.form`: username, email, temp password, role dropdown
- Super admins see all 3 roles; admins see only admin + viewer
- Per-user row: Edit, Deactivate/Reactivate, Reset Password buttons
- Safety checks: can't deactivate self, can't remove last super_admin

**Tab 2 — Permissions:**
- User selector dropdown
- Checklist of all permission keys
- Pre-filled from role defaults, toggleable
- "Reset to Defaults" button
- Visual indicator for custom overrides

**Tab 3 — Scheduled Reports:**
- `st.dataframe` showing all reports with next run time
- "Add Report" form: name, report_type (from REPORT_CATALOG), frequency, day, hour, product filter, sheet ID, webhook
- Per-report: Edit, Deactivate, "Send Now" button
- "Send Now" calls `scheduler.run_now(report_id)`

**Step 2: Gate page with permissions**

```python
require_auth()
require_permission("admin:manage_users")
```

**Step 3: Test manually**

Start the app, log in as admin, verify all three tabs work.

**Step 4: Remove old Report Settings page**

Delete `pages/12_Report_Settings.py`.

**Step 5: Commit**

```bash
git add pages/13_User_Management.py
git rm pages/12_Report_Settings.py
git commit -m "feat: add User Management page with users, permissions, scheduled reports

Three-tab admin page replacing old Report Settings.
Tab 1: User CRUD with role hierarchy enforcement.
Tab 2: Feature-level permission overrides per user.
Tab 3: Scheduled report configuration with Send Now."
```

---

### Task 15: Final integration test + cleanup

**Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All pass

**Step 2: Lint**

Run: `ruff check . --fix`
Expected: Clean

**Step 3: Security scan**

Run Snyk code scan on the project.

**Step 4: Manual smoke test**

1. Start app fresh (no auth.db) — verify migration from secrets.toml works
2. Log in as admin → User Management → create a viewer user
3. Log in as viewer → verify restricted pages are blocked
4. As admin, create a scheduled report → "Send Now" → verify Google Sheet + Slack delivery
5. Verify renewals report shows upcoming renewals/cancellations

**Step 5: Final commit**

```bash
git add -A
git commit -m "chore: final integration cleanup after scheduled reports + user management"
```
