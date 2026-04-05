# Auth Replacement & Report Scheduling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace broken streamlit-authenticator with custom login, redesign report scheduling with day-of-week checkboxes and local timezone display, and switch Slack delivery from webhooks to bot DMs.

**Architecture:** Custom auth via `st.form` + `auth_db.authenticate()` + `st.session_state`. Report schedules stored as `schedule_type` (weekly/monthly) + `schedule_days` (comma-separated weekday indices) + `timezone`. Slack bot token in secrets.toml, user Slack IDs in users table, DMs via `chat.postMessage`.

**Tech Stack:** Python 3.12, Streamlit, SQLite, bcrypt, requests (for Slack API), APScheduler

---

### Task 1: Remove streamlit-authenticator dependency

**Files:**
- Modify: `requirements.txt:8`

**Step 1: Remove streamlit-authenticator from requirements**

In `requirements.txt`, remove line 8 (`streamlit-authenticator>=0.4.0,<0.5`). The file should become:

```
streamlit>=1.54,<1.55
pandas>=2.3,<2.4
plotly>=6.5,<6.6
requests>=2.32,<2.33
openpyxl>=3.1,<3.2
gspread>=6.0,<6.1
google-auth>=2.48,<2.49
bcrypt>=4.0,<5.0
apscheduler>=3.10,<4.0
```

**Step 2: Uninstall the packages**

Run: `pip uninstall streamlit-authenticator extra-streamlit-components -y`

**Step 3: Reinstall from requirements**

Run: `pip install -r requirements.txt`

**Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: remove streamlit-authenticator dependency"
```

---

### Task 2: Implement custom login in auth.py

**Files:**
- Modify: `auth.py` (full rewrite of `require_auth()`)
- Test: `tests/test_auth_login.py` (new)

**Step 1: Write the failing tests**

Create `tests/test_auth_login.py`:

```python
"""Tests for custom auth login flow."""

from unittest.mock import MagicMock, patch

import pytest

from auth_db import AuthDB


@pytest.fixture()
def db(tmp_path):
    return AuthDB(db_path=str(tmp_path / "test_auth.db"))


class TestRequireAuth:
    """Test the custom login logic (unit tests, no Streamlit runner)."""

    def test_authenticate_valid_user(self, db):
        """auth_db.authenticate returns user dict for valid credentials."""
        db.create_user("alice", "a@x.com", "password123", "viewer")
        user = db.authenticate("alice", "password123")
        assert user is not None
        assert user["username"] == "alice"

    def test_authenticate_wrong_password(self, db):
        db.create_user("alice", "a@x.com", "password123", "viewer")
        assert db.authenticate("alice", "wrong") is None

    def test_authenticate_inactive_user(self, db):
        db.create_user("alice", "a@x.com", "password123", "viewer")
        db.deactivate_user("alice")
        assert db.authenticate("alice", "password123") is None

    def test_authenticate_nonexistent(self, db):
        assert db.authenticate("ghost", "pw") is None
```

**Step 2: Run tests to verify they pass**

Run: `pytest tests/test_auth_login.py -v`
Expected: PASS (these test auth_db which already works)

**Step 3: Rewrite auth.py**

Replace the entire `require_auth()` function and remove all `streamlit_authenticator` imports. The new `auth.py`:

```python
"""Authentication gate backed by AuthDB (SQLite) — custom login, no cookies."""

from __future__ import annotations

import logging

import streamlit as st

from auth_db import AuthDB

logger = logging.getLogger(__name__)


# -- Singleton ---------------------------------------------------------------


@st.cache_resource
def get_auth_db() -> AuthDB:
    """Return the shared AuthDB instance (creates auth.db on first call)."""
    db = AuthDB()
    _migrate_from_secrets(db)
    return db


def _migrate_from_secrets(db: AuthDB) -> None:
    """One-time migration: copy users from secrets.toml into auth.db if empty."""
    if db.list_users():
        return

    try:
        creds = st.secrets["auth"]["credentials"]["usernames"]
    except (KeyError, FileNotFoundError):
        return

    for username, user_data in creds.items():
        role = user_data.get("role", "viewer")
        if role in ("admin", "super_admin"):
            db_role = "super_admin"
        elif role == "admin":
            db_role = "admin"
        else:
            db_role = "viewer"

        try:
            db.conn.execute(
                "INSERT INTO users (username, email, password_hash, role, created_by) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    username,
                    user_data.get("email", ""),
                    user_data.get("password", ""),
                    db_role,
                    "migration",
                ),
            )
            db.conn.commit()
            logger.info("Migrated user from secrets.toml: %s (role=%s)", username, db_role)
        except Exception:
            logger.exception("Failed to migrate user: %s", username)


# -- Auth Gate ---------------------------------------------------------------


def require_auth() -> None:
    """Show login form if not authenticated. Session-state based, no cookies."""
    if st.session_state.get("authentication_status") is True:
        _render_logout_button()
        return

    auth_db = get_auth_db()
    users = auth_db.list_users()
    if not users:
        st.error(
            "No users configured. Add users to auth.db or "
            "configure `[auth]` in `.streamlit/secrets.toml`."
        )
        st.stop()
        return

    st.title("Login")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", use_container_width=True)

    if submitted:
        if not username or not password:
            st.warning("Please enter your username and password.")
            st.stop()
            return

        user = auth_db.authenticate(username, password)
        if user is None:
            st.error("Username or password is incorrect.")
            st.stop()
            return

        # Success — set session state
        st.session_state["authentication_status"] = True
        st.session_state["username"] = user["username"]
        st.session_state["name"] = user["username"]

        # Load permissions
        try:
            st.session_state["permissions"] = auth_db.get_permissions(username)
            st.session_state["user_role"] = user["role"]
        except Exception:
            logger.exception("Failed to load permissions for %s", username)
            st.session_state["permissions"] = set()
            st.session_state["user_role"] = "viewer"

        st.rerun()

    st.stop()


def _render_logout_button() -> None:
    """Render logout button in sidebar."""
    if st.sidebar.button("Logout"):
        for key in ["authentication_status", "username", "name", "permissions", "user_role"]:
            st.session_state.pop(key, None)
        st.rerun()


# -- Permission Helpers ------------------------------------------------------


def has_permission(key: str) -> bool:
    """Check if the current user has a specific permission."""
    perms = st.session_state.get("permissions", set())
    return key in perms


def require_permission(key: str) -> None:
    """Stop the page if the current user lacks the given permission."""
    if not has_permission(key):
        st.error("You don't have permission to access this page.")
        st.stop()


def get_user_role(username: str | None = None) -> str:
    """Return the role of the given user (or current user from session state)."""
    if username is None:
        return st.session_state.get("user_role", "viewer")
    try:
        auth_db = get_auth_db()
        user = auth_db.get_user(username)
        return user["role"] if user else "viewer"
    except Exception:
        return "viewer"


def is_admin(username: str | None = None) -> bool:
    """Check if user has admin or super_admin role."""
    role = get_user_role(username)
    return role in ("admin", "super_admin")


def require_admin() -> None:
    """Stop the page if the current user is not an admin/super_admin."""
    if not is_admin():
        st.error("Access restricted to administrators.")
        st.stop()
```

**Step 4: Run all existing tests**

Run: `pytest tests/ -v`
Expected: All tests pass. Some tests mock streamlit-authenticator — those may need updating if they import from auth.py directly.

**Step 5: Commit**

```bash
git add auth.py tests/test_auth_login.py
git commit -m "feat: replace streamlit-authenticator with custom login form"
```

---

### Task 3: Add slack_user_id to users table

**Files:**
- Modify: `auth_db.py:83-126` (schema), `auth_db.py:136-146` (_row_to_user_dict), `auth_db.py:159-185` (create_user, get_user), `auth_db.py:206-233` (update_user)
- Test: `tests/test_auth_db.py` (add new tests)

**Step 1: Write failing tests**

Add to `tests/test_auth_db.py` in `TestUserCRUD`:

```python
    def test_slack_user_id_default_none(self, db):
        user = db.create_user("alice", "alice@example.com", "secret123", "viewer")
        assert user.get("slack_user_id") is None

    def test_update_slack_user_id(self, db):
        db.create_user("alice", "alice@example.com", "secret123", "viewer")
        db.update_user("alice", slack_user_id="U12345ABC")
        user = db.get_user("alice")
        assert user["slack_user_id"] == "U12345ABC"

    def test_update_slack_user_id_to_none(self, db):
        db.create_user("alice", "alice@example.com", "secret123", "viewer")
        db.update_user("alice", slack_user_id="U12345ABC")
        db.update_user("alice", slack_user_id=None)
        user = db.get_user("alice")
        assert user["slack_user_id"] is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_auth_db.py::TestUserCRUD::test_slack_user_id_default_none -v`
Expected: FAIL (slack_user_id not in schema)

**Step 3: Update auth_db.py schema and methods**

In `_init_schema()`, after the `users` CREATE TABLE, add migration:

```python
        # Migration: add slack_user_id column
        try:
            cur.execute("ALTER TABLE users ADD COLUMN slack_user_id TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
```

In `_row_to_user_dict()`, add:

```python
        "slack_user_id": row["slack_user_id"] if "slack_user_id" in row.keys() else None,
```

In `get_user()` and `list_users()`, add `slack_user_id` to the SELECT column list.

In `update_user()`, add `slack_user_id` parameter:

```python
    def update_user(
        self,
        username: str,
        email: str | None = None,
        role: str | None = None,
        slack_user_id: str | None = ...,  # sentinel: ... means "not provided"
    ) -> None:
```

Use a sentinel pattern: `_UNSET = object()` at module level. Default `slack_user_id=_UNSET`. If not `_UNSET`, update it (allowing `None` to clear it):

```python
        if slack_user_id is not _UNSET:
            self.conn.execute(
                "UPDATE users SET slack_user_id = ? WHERE username = ?",
                (slack_user_id, username),
            )
```

**Step 4: Run tests**

Run: `pytest tests/test_auth_db.py -v`
Expected: All pass including new tests

**Step 5: Commit**

```bash
git add auth_db.py tests/test_auth_db.py
git commit -m "feat: add slack_user_id column to users table"
```

---

### Task 4: Add Slack DM delivery function

**Files:**
- Modify: `notifications.py` (add `send_slack_dm()`)
- Test: `tests/test_report_delivery.py` (add DM tests)

**Step 1: Write failing tests**

Add to `tests/test_report_delivery.py`:

```python
from notifications import send_slack_dm


class TestSendSlackDM:
    @patch("notifications.requests.post")
    def test_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.json.return_value = {"ok": True}
        mock_post.return_value.raise_for_status = MagicMock()
        result = send_slack_dm(
            bot_token="xoxb-test-token",
            user_id="U12345ABC",
            report_name="Weekly Revenue",
            sheet_url="https://docs.google.com/spreadsheets/d/abc123",
        )
        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["headers"]["Authorization"] == "Bearer xoxb-test-token"
        payload = call_kwargs[1]["json"]
        assert payload["channel"] == "U12345ABC"

    @patch("notifications.requests.post")
    def test_failure(self, mock_post):
        mock_post.side_effect = Exception("Connection error")
        result = send_slack_dm(
            bot_token="xoxb-test-token",
            user_id="U12345ABC",
            report_name="Test",
            sheet_url="https://example.com",
        )
        assert result is False

    def test_missing_bot_token(self):
        result = send_slack_dm(
            bot_token="",
            user_id="U12345ABC",
            report_name="Test",
            sheet_url="https://example.com",
        )
        assert result is False

    def test_missing_user_id(self):
        result = send_slack_dm(
            bot_token="xoxb-test-token",
            user_id="",
            report_name="Test",
            sheet_url="https://example.com",
        )
        assert result is False
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_report_delivery.py::TestSendSlackDM -v`
Expected: FAIL (ImportError, function doesn't exist)

**Step 3: Implement send_slack_dm in notifications.py**

Add to `notifications.py`:

```python
def send_slack_dm(
    bot_token: str,
    user_id: str,
    report_name: str,
    sheet_url: str,
) -> bool:
    """Send a report DM to a Slack user via chat.postMessage."""
    if not bot_token or not user_id:
        logger.error("Slack bot_token or user_id missing")
        return False

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Report: {report_name}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"<{sheet_url}|Open in Google Sheets>"}},
    ]

    try:
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {bot_token}"},
            json={"channel": user_id, "blocks": blocks, "text": f"Report: {report_name}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            logger.error("Slack API error: %s", data.get("error", "unknown"))
            return False
        logger.info("Slack DM sent to %s: %s", user_id, report_name)
        return True
    except Exception:
        logger.exception("Failed to send Slack DM to %s: %s", user_id, report_name)
        return False
```

**Step 4: Run tests**

Run: `pytest tests/test_report_delivery.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add notifications.py tests/test_report_delivery.py
git commit -m "feat: add Slack DM delivery via bot token"
```

---

### Task 5: Update scheduled_reports schema for new schedule model

**Files:**
- Modify: `auth_db.py:107-123` (scheduled_reports schema), `auth_db.py:344-362` (_row_to_report_dict), `auth_db.py:364-402` (create_scheduled_report), `auth_db.py:425-459` (update_scheduled_report)
- Test: `tests/test_auth_db.py` (update TestScheduledReports)

**Step 1: Write failing tests**

Replace `TestScheduledReports` in `tests/test_auth_db.py` with updated tests:

```python
class TestScheduledReports:
    def test_create_weekly_report(self, db):
        report = db.create_scheduled_report(
            name="Weekday Revenue",
            report_type="daily_metrics",
            schedule_type="weekly",
            schedule_days="0,1,2,3,4",
            hour_utc=14,
            timezone="America/Los_Angeles",
            spreadsheet_id="sheet123",
            created_by="alice",
        )
        assert report["name"] == "Weekday Revenue"
        assert report["schedule_type"] == "weekly"
        assert report["schedule_days"] == "0,1,2,3,4"
        assert report["hour_utc"] == 14
        assert report["timezone"] == "America/Los_Angeles"
        assert report["is_active"] is True

    def test_create_monthly_report(self, db):
        report = db.create_scheduled_report(
            name="Monthly Summary",
            report_type="daily_metrics",
            schedule_type="monthly",
            day_of_month=1,
            hour_utc=9,
            timezone="US/Eastern",
            spreadsheet_id="sheet456",
            created_by="bob",
        )
        assert report["schedule_type"] == "monthly"
        assert report["day_of_month"] == 1

    def test_list_active_reports(self, db):
        db.create_scheduled_report(
            name="R1", report_type="t", schedule_type="weekly",
            schedule_days="0", hour_utc=12, timezone="UTC",
            spreadsheet_id="s1", created_by="alice",
        )
        r2 = db.create_scheduled_report(
            name="R2", report_type="t", schedule_type="weekly",
            schedule_days="0", hour_utc=12, timezone="UTC",
            spreadsheet_id="s2", created_by="bob",
        )
        db.deactivate_scheduled_report(r2["id"])

        all_reports = db.list_scheduled_reports(active_only=False)
        assert len(all_reports) == 2

        active_reports = db.list_scheduled_reports(active_only=True)
        assert len(active_reports) == 1
        assert active_reports[0]["name"] == "R1"

    def test_deactivate_report(self, db):
        report = db.create_scheduled_report(
            name="R1", report_type="t", schedule_type="weekly",
            schedule_days="0", hour_utc=12, timezone="UTC",
            spreadsheet_id="s1", created_by="alice",
        )
        db.deactivate_scheduled_report(report["id"])
        updated = db.get_scheduled_report(report["id"])
        assert updated["is_active"] is False

    def test_update_report(self, db):
        report = db.create_scheduled_report(
            name="R1", report_type="t", schedule_type="weekly",
            schedule_days="0", hour_utc=12, timezone="UTC",
            spreadsheet_id="s1", created_by="alice",
        )
        db.update_scheduled_report(report["id"], name="Updated", hour_utc=15)
        updated = db.get_scheduled_report(report["id"])
        assert updated["name"] == "Updated"
        assert updated["hour_utc"] == 15

    def test_get_nonexistent_report(self, db):
        assert db.get_scheduled_report(999) is None

    def test_update_ignores_unknown_columns(self, db):
        report = db.create_scheduled_report(
            name="R1", report_type="t", schedule_type="weekly",
            schedule_days="0", hour_utc=12, timezone="UTC",
            spreadsheet_id="s1", created_by="alice",
        )
        db.update_scheduled_report(report["id"], bogus_col="value")
        fetched = db.get_scheduled_report(report["id"])
        assert fetched["name"] == "R1"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_auth_db.py::TestScheduledReports -v`
Expected: FAIL (schema mismatch, new columns don't exist)

**Step 3: Update auth_db.py**

Modify `_init_schema()` — add migration columns after existing CREATE TABLE:

```python
        # Migration: add new schedule columns
        for col, default in [
            ("schedule_type TEXT", None),
            ("schedule_days TEXT", None),
            ("timezone TEXT DEFAULT 'America/Los_Angeles'", None),
        ]:
            try:
                col_name = col.split()[0]
                cur.execute(f"ALTER TABLE scheduled_reports ADD COLUMN {col}")  # noqa: S608
            except sqlite3.OperationalError:
                pass  # already exists

        # Migrate old frequency values to new schedule_type/schedule_days
        cur.execute("""
            UPDATE scheduled_reports
            SET schedule_type = CASE
                WHEN frequency = 'daily' THEN 'weekly'
                WHEN frequency = 'weekly' THEN 'weekly'
                WHEN frequency = 'monthly' THEN 'monthly'
                ELSE 'weekly'
            END,
            schedule_days = CASE
                WHEN frequency = 'daily' THEN '0,1,2,3,4,5,6'
                WHEN frequency = 'weekly' THEN CAST(COALESCE(day_of_week, 0) AS TEXT)
                ELSE NULL
            END,
            timezone = COALESCE(timezone, 'America/Los_Angeles')
            WHERE schedule_type IS NULL
        """)
        self.conn.commit()
```

Update `_row_to_report_dict()` to include new fields:

```python
    def _row_to_report_dict(self, row: sqlite3.Row) -> dict:
        keys = row.keys()
        return {
            "id": row["id"],
            "name": row["name"],
            "report_type": row["report_type"],
            "frequency": row["frequency"] if "frequency" in keys else None,
            "schedule_type": row["schedule_type"] if "schedule_type" in keys else None,
            "schedule_days": row["schedule_days"] if "schedule_days" in keys else None,
            "day_of_week": row["day_of_week"] if "day_of_week" in keys else None,
            "day_of_month": row["day_of_month"],
            "hour_utc": row["hour_utc"],
            "timezone": row["timezone"] if "timezone" in keys else "America/Los_Angeles",
            "product_filter": row["product_filter"],
            "date_range_days": row["date_range_days"],
            "spreadsheet_id": row["spreadsheet_id"],
            "slack_webhook": row["slack_webhook"] if "slack_webhook" in keys else None,
            "slack_channel": row["slack_channel"] if "slack_channel" in keys else None,
            "created_by": row["created_by"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
        }
```

Update `create_scheduled_report()` signature — add `schedule_type`, `schedule_days`, `timezone` params, make `slack_webhook` optional (default `""`), make `frequency` optional (default `None`, computed from `schedule_type`):

```python
    def create_scheduled_report(
        self,
        name: str,
        report_type: str,
        schedule_type: str,
        hour_utc: int,
        spreadsheet_id: str,
        created_by: str,
        schedule_days: str | None = None,
        day_of_month: int | None = None,
        timezone: str = "America/Los_Angeles",
        product_filter: str | None = None,
        date_range_days: int = 30,
        slack_webhook: str = "",
        slack_channel: str | None = None,
        # Legacy compat
        frequency: str | None = None,
        day_of_week: int | None = None,
    ) -> dict:
```

Compute `frequency` from `schedule_type` for backward compat:

```python
        if frequency is None:
            frequency = "weekly" if schedule_type == "weekly" else "monthly"
```

Update `update_scheduled_report()` allowed_cols to include `schedule_type`, `schedule_days`, `timezone`.

**Step 4: Run tests**

Run: `pytest tests/test_auth_db.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add auth_db.py tests/test_auth_db.py
git commit -m "feat: add schedule_type/schedule_days/timezone to scheduled_reports"
```

---

### Task 6: Update report_scheduler for new schedule model + Slack DM

**Files:**
- Modify: `report_scheduler.py` (trigger building + DM delivery)
- Test: `tests/test_report_scheduler.py` (update tests)

**Step 1: Write failing tests**

Replace tests in `tests/test_report_scheduler.py`:

```python
"""Tests for report_scheduler.py — scheduler job management."""

from unittest.mock import MagicMock, patch

import pytest

from auth_db import AuthDB
from report_scheduler import ReportScheduler


@pytest.fixture()
def auth_db(tmp_path):
    return AuthDB(db_path=str(tmp_path / "test_auth.db"))


@pytest.fixture()
def mock_cache():
    import pandas as pd
    cache = MagicMock()
    cache.get_orders_df.return_value = pd.DataFrame()
    cache.get_charges_df.return_value = pd.DataFrame()
    cache.get_subscriptions_df.return_value = pd.DataFrame()
    cache.get_products_df.return_value = pd.DataFrame()
    return cache


class TestReportScheduler:
    def test_start_with_no_reports(self, auth_db, mock_cache):
        scheduler = ReportScheduler(auth_db, mock_cache)
        scheduler.start()
        assert scheduler.scheduler.running
        scheduler.scheduler.shutdown(wait=False)

    def test_add_and_remove_job(self, auth_db, mock_cache):
        report = auth_db.create_scheduled_report(
            name="Test", report_type="daily_metrics",
            schedule_type="weekly", schedule_days="0,2,4",
            hour_utc=9, timezone="UTC",
            spreadsheet_id="s1", created_by="alice",
        )
        scheduler = ReportScheduler(auth_db, mock_cache)
        scheduler.start()
        assert scheduler.scheduler.get_job(f"report_{report['id']}") is not None
        scheduler.remove_report(report["id"])
        assert scheduler.scheduler.get_job(f"report_{report['id']}") is None
        scheduler.scheduler.shutdown(wait=False)

    @patch("report_scheduler.upload_report")
    @patch("report_scheduler.send_slack_dm")
    def test_execute_report_sends_dm(self, mock_dm, mock_upload, auth_db, mock_cache):
        """Report execution should use Slack DM when creator has slack_user_id."""
        mock_upload.return_value = "https://docs.google.com/spreadsheets/d/s1"
        mock_dm.return_value = True

        auth_db.create_user("alice", "a@x.com", "pw", "admin")
        auth_db.update_user("alice", slack_user_id="U12345ABC")

        report = auth_db.create_scheduled_report(
            name="Test", report_type="daily_metrics",
            schedule_type="weekly", schedule_days="0",
            hour_utc=9, timezone="UTC",
            spreadsheet_id="s1", created_by="alice",
        )
        scheduler = ReportScheduler(auth_db, mock_cache, slack_bot_token="xoxb-test")
        scheduler.run_now(report["id"])

        mock_upload.assert_called_once()
        mock_dm.assert_called_once_with(
            bot_token="xoxb-test",
            user_id="U12345ABC",
            report_name="Test",
            sheet_url="https://docs.google.com/spreadsheets/d/s1",
        )

    def test_execute_inactive_report_skips(self, auth_db, mock_cache):
        report = auth_db.create_scheduled_report(
            name="Test", report_type="daily_metrics",
            schedule_type="weekly", schedule_days="0",
            hour_utc=9, timezone="UTC",
            spreadsheet_id="s1", created_by="alice",
        )
        auth_db.deactivate_scheduled_report(report["id"])
        scheduler = ReportScheduler(auth_db, mock_cache)
        scheduler.run_now(report["id"])  # should not raise
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_report_scheduler.py -v`
Expected: FAIL (signature changes)

**Step 3: Update report_scheduler.py**

```python
"""APScheduler-based report scheduler — runs as background thread in Streamlit."""

from __future__ import annotations

import datetime
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from auth_db import AuthDB
from cache import SamCartCache
from gsheets import upload_report
from notifications import send_slack_dm, send_slack_sheet_link
from report_catalog import REPORT_CATALOG, generate_report

logger = logging.getLogger(__name__)


class ReportScheduler:
    """Manages scheduled report jobs backed by auth_db."""

    def __init__(self, auth_db: AuthDB, cache: SamCartCache, slack_bot_token: str = ""):
        self.auth_db = auth_db
        self.cache = cache
        self.slack_bot_token = slack_bot_token
        self.scheduler = BackgroundScheduler()

    def start(self) -> None:
        reports = self.auth_db.list_scheduled_reports(active_only=True)
        for report in reports:
            self._add_job(report)
        self.scheduler.start()

    def _add_job(self, report: dict) -> None:
        trigger = self._build_trigger(report)
        self.scheduler.add_job(
            self._execute_report,
            trigger=trigger,
            args=[report["id"]],
            id=f"report_{report['id']}",
            replace_existing=True,
        )

    def _build_trigger(self, report: dict) -> CronTrigger:
        """Build a CronTrigger from report config (new or legacy schema)."""
        schedule_type = report.get("schedule_type") or report.get("frequency", "weekly")

        if schedule_type == "monthly":
            return CronTrigger(
                hour=report["hour_utc"],
                day=report.get("day_of_month", 1),
            )

        # Weekly: fire daily at hour_utc (job checks if today matches schedule_days)
        return CronTrigger(hour=report["hour_utc"])

    def _execute_report(self, report_id: int) -> None:
        """Run a single report: generate -> upload -> notify."""
        report = self.auth_db.get_scheduled_report(report_id)
        if not report or not report["is_active"]:
            return

        # For weekly reports, check if today is a scheduled day
        schedule_type = report.get("schedule_type") or report.get("frequency", "weekly")
        if schedule_type == "weekly":
            schedule_days = report.get("schedule_days", "0,1,2,3,4,5,6")
            if schedule_days:
                today_weekday = datetime.datetime.now(tz=datetime.timezone.utc).weekday()
                allowed_days = [int(d.strip()) for d in schedule_days.split(",") if d.strip()]
                if today_weekday not in allowed_days:
                    return

        if report["report_type"] not in REPORT_CATALOG:
            logger.error("Unknown report type: %s", report["report_type"])
            return

        product_filter = (
            report["product_filter"].split(",")
            if report.get("product_filter")
            else None
        )

        try:
            df = generate_report(
                report["report_type"],
                self.cache,
                date_range_days=report.get("date_range_days", 30),
                product_filter=product_filter,
            )
            sheet_url = upload_report(
                df, report["spreadsheet_id"], report["name"],
            )

            # Try Slack DM first, fall back to webhook
            delivered = False
            if self.slack_bot_token and report.get("created_by"):
                creator = self.auth_db.get_user(report["created_by"])
                if creator and creator.get("slack_user_id"):
                    delivered = send_slack_dm(
                        bot_token=self.slack_bot_token,
                        user_id=creator["slack_user_id"],
                        report_name=report["name"],
                        sheet_url=sheet_url,
                    )

            # Fallback to legacy webhook
            if not delivered and report.get("slack_webhook"):
                send_slack_sheet_link(
                    report["slack_webhook"], report["name"], sheet_url,
                )

            logger.info("Report delivered: %s", report["name"])
        except Exception:
            logger.exception("Failed to execute report: %s", report["name"])

    def reload_report(self, report_id: int) -> None:
        job_id = f"report_{report_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
        report = self.auth_db.get_scheduled_report(report_id)
        if report and report["is_active"]:
            self._add_job(report)

    def remove_report(self, report_id: int) -> None:
        job_id = f"report_{report_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

    def run_now(self, report_id: int) -> None:
        self._execute_report(report_id)
```

**Step 4: Run tests**

Run: `pytest tests/test_report_scheduler.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add report_scheduler.py tests/test_report_scheduler.py
git commit -m "feat: update scheduler for day-of-week model and Slack DM delivery"
```

---

### Task 7: Update shared.py to pass Slack bot token to scheduler

**Files:**
- Modify: `shared.py:121-127`

**Step 1: Update get_scheduler()**

```python
@st.cache_resource
def get_scheduler():
    """Start and return the shared ReportScheduler."""
    from report_scheduler import ReportScheduler
    slack_cfg = st.secrets.get("slack", {})
    bot_token = slack_cfg.get("bot_token", "")
    scheduler = ReportScheduler(get_auth_db(), get_cache(), slack_bot_token=bot_token)
    scheduler.start()
    return scheduler
```

**Step 2: Run all tests**

Run: `pytest tests/ -v`
Expected: All pass

**Step 3: Commit**

```bash
git add shared.py
git commit -m "feat: pass Slack bot token to scheduler from secrets"
```

---

### Task 8: Redesign the Scheduled Reports tab in User Management page

**Files:**
- Modify: `pages/13_User_Management.py:202-309` (Tab 3 — Scheduled Reports)

**Step 1: Add timezone detection JavaScript**

At the top of the Scheduled Reports tab, add browser timezone detection:

```python
import streamlit.components.v1 as components

# Detect browser timezone
if "user_timezone" not in st.session_state:
    components.html(
        """<script>
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        window.parent.postMessage({type: 'streamlit:setComponentValue', value: tz}, '*');
        </script>""",
        height=0,
    )
    # Fallback — use this approach with query params
```

NOTE: Streamlit's `components.html` can't directly set session state. Instead, use the `streamlit-js-eval` pattern or a simpler approach: use `st.selectbox` with common US timezones, defaulting to "America/Los_Angeles". This is more reliable:

```python
    COMMON_TIMEZONES = [
        "America/Los_Angeles",
        "America/Denver",
        "America/Chicago",
        "America/New_York",
        "UTC",
    ]
```

**Step 2: Rewrite the report display section**

For each report in the list, display schedule in local time using `datetime` and `zoneinfo`:

```python
from zoneinfo import ZoneInfo

def _format_schedule(report: dict) -> str:
    """Format schedule for display in the report's timezone."""
    tz_name = report.get("timezone", "America/Los_Angeles")
    try:
        tz = ZoneInfo(tz_name)
    except KeyError:
        tz = ZoneInfo("America/Los_Angeles")

    # Convert hour_utc to local
    utc_time = datetime.time(report["hour_utc"], 0)
    utc_dt = datetime.datetime.combine(datetime.date.today(), utc_time, tzinfo=ZoneInfo("UTC"))
    local_dt = utc_dt.astimezone(tz)
    local_time = local_dt.strftime("%-I:%M %p")  # Use %#I on Windows
    tz_abbr = local_dt.strftime("%Z")

    schedule_type = report.get("schedule_type", "weekly")
    if schedule_type == "monthly":
        dom = report.get("day_of_month", 1)
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(dom % 10, "th")
        if 11 <= dom <= 13:
            suffix = "th"
        return f"Monthly on the {dom}{suffix} at {local_time} {tz_abbr}"

    days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    schedule_days = report.get("schedule_days", "0,1,2,3,4,5,6")
    if schedule_days:
        day_indices = sorted(int(d.strip()) for d in schedule_days.split(",") if d.strip())
        day_names = [days_map.get(d, "?") for d in day_indices]
        if len(day_names) == 7:
            return f"Every day at {local_time} {tz_abbr}"
        return f"{', '.join(day_names)} at {local_time} {tz_abbr}"
    return f"Every day at {local_time} {tz_abbr}"
```

**Step 3: Rewrite the create report form**

```python
    with st.form("add_report_form"):
        rpt_name = st.text_input("Report Name")
        rpt_type = st.selectbox(
            "Report Type",
            list(REPORT_CATALOG.keys()),
            format_func=lambda k: REPORT_CATALOG[k]["name"],
        )

        rpt_schedule_type = st.radio("Schedule", ["Weekly", "Monthly"], horizontal=True)

        if rpt_schedule_type == "Weekly":
            st.caption("Select which days to receive the report:")
            day_cols = st.columns(7)
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            selected_days = []
            for i, (col, name) in enumerate(zip(day_cols, day_names)):
                if col.checkbox(name, value=i < 5, key=f"day_{i}"):
                    selected_days.append(i)
        else:
            rpt_dom = st.number_input("Day of month", min_value=1, max_value=28, value=1)

        COMMON_TIMEZONES = [
            "America/Los_Angeles",
            "America/Denver",
            "America/Chicago",
            "America/New_York",
            "UTC",
        ]
        rpt_tz = st.selectbox("Timezone", COMMON_TIMEZONES, index=0)
        rpt_time = st.time_input("Delivery time", value=datetime.time(7, 0))

        rpt_range = st.number_input("Date range (days)", min_value=1, value=30)
        rpt_product = st.text_input("Product filter (comma-separated, blank=all)")
        rpt_sheet = st.text_input("Google Spreadsheet ID")

        rpt_submitted = st.form_submit_button("Create Report")

        if rpt_submitted:
            if not rpt_name or not rpt_sheet:
                st.error("Name and Spreadsheet ID are required.")
            elif rpt_schedule_type == "Weekly" and not selected_days:
                st.error("Select at least one day.")
            else:
                # Convert local time to UTC
                from zoneinfo import ZoneInfo
                local_tz = ZoneInfo(rpt_tz)
                local_dt = datetime.datetime.combine(
                    datetime.date.today(), rpt_time, tzinfo=local_tz,
                )
                utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
                hour_utc = utc_dt.hour

                try:
                    report = auth_db.create_scheduled_report(
                        name=rpt_name,
                        report_type=rpt_type,
                        schedule_type=rpt_schedule_type.lower(),
                        schedule_days=",".join(str(d) for d in selected_days) if rpt_schedule_type == "Weekly" else None,
                        day_of_month=int(rpt_dom) if rpt_schedule_type == "Monthly" else None,
                        hour_utc=hour_utc,
                        timezone=rpt_tz,
                        spreadsheet_id=rpt_sheet,
                        created_by=current_user,
                        product_filter=rpt_product or None,
                        date_range_days=int(rpt_range),
                    )
                    try:
                        get_scheduler().reload_report(report["id"])
                    except Exception:
                        pass
                    st.success(f"Created report: {rpt_name}")
                    st.rerun()
                except Exception:
                    logger.exception("Failed to create report")
                    st.error("Failed to create report. Check logs.")
```

**Step 4: Add Slack User ID field to the Users tab**

In Tab 1 (Users), within the user expander, add a field to edit Slack User ID:

```python
                # Slack User ID
                current_slack_id = ""
                row = auth_db.conn.execute(
                    "SELECT slack_user_id FROM users WHERE username = ?",
                    (user["username"],),
                ).fetchone()
                if row and row["slack_user_id"]:
                    current_slack_id = row["slack_user_id"]

                new_slack_id = st.text_input(
                    "Slack User ID",
                    value=current_slack_id,
                    key=f"slack_{user['username']}",
                    help="Find in Slack: Profile > ⋮ > Copy member ID",
                )
                if new_slack_id != current_slack_id:
                    if st.button("Update Slack ID", key=f"slack_btn_{user['username']}"):
                        auth_db.update_user(
                            user["username"],
                            slack_user_id=new_slack_id or None,
                        )
                        st.success("Slack ID updated.")
                        st.rerun()
```

**Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: All pass

**Step 6: Lint**

Run: `ruff check . --fix`

**Step 7: Commit**

```bash
git add pages/13_User_Management.py
git commit -m "feat: redesign report scheduling with day checkboxes, local time, Slack DM"
```

---

### Task 9: Update secrets.toml.example

**Files:**
- Modify: `.streamlit/secrets.toml.example`

**Step 1: Update the example**

```toml
# Copy this file to .streamlit/secrets.toml and fill in real values
SAMCART_API_KEY = "your_key_here"

[auth]
cookie_name = "samcart_analytics"
cookie_key = "GENERATE_A_RANDOM_32_CHAR_STRING"
cookie_expiry_days = 7

[auth.credentials.usernames.admin]
email = "admin@example.com"
name = "Admin"
# IMPORTANT: use single quotes for the bcrypt hash — double quotes corrupt \b
password = '$2b$12$BCRYPT_HASHED_PASSWORD_HERE'

[slack]
bot_token = "xoxb-YOUR-BOT-TOKEN"
```

**Step 2: Commit**

```bash
git add .streamlit/secrets.toml.example
git commit -m "docs: add slack bot_token to secrets.toml example"
```

---

### Task 10: Final integration test and lint

**Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All pass

**Step 2: Lint**

Run: `ruff check . --fix`

**Step 3: Manual smoke test**

Run: `streamlit run app.py`
Verify:
- Login form appears (no CookieManager error)
- Can log in with existing credentials
- User Management > Users tab shows Slack User ID field
- User Management > Scheduled Reports tab shows new form with day checkboxes
- Creating a report shows correct local time in the list

**Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: integration fixes from smoke testing"
```
