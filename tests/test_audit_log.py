"""Tests for audit log functionality in cache.py."""

import sqlite3

import pandas as pd
import pytest

from cache import SamCartCache


@pytest.fixture()
def cache():
    """Create a SamCartCache with an in-memory DB."""
    c = SamCartCache.__new__(SamCartCache)
    c.db_path = ":memory:"
    c.conn = sqlite3.connect(":memory:", check_same_thread=False)
    c.conn.execute("PRAGMA journal_mode=WAL")
    c._init_schema()
    return c


class TestLogAuditEvent:
    def test_insert_and_query(self, cache):
        """Insert an audit event and retrieve it via get_audit_log_df."""
        cache.log_audit_event(
            username="admin",
            ip_address="127.0.0.1",
            action="login",
            resource="dashboard",
            detail="Successful login",
            outcome="auto",
        )
        df = cache.get_audit_log_df(days=1)
        assert len(df) == 1
        assert df.iloc[0]["username"] == "admin"
        assert df.iloc[0]["ip_address"] == "127.0.0.1"
        assert df.iloc[0]["action"] == "login"
        assert df.iloc[0]["resource"] == "dashboard"
        assert df.iloc[0]["detail"] == "Successful login"
        assert df.iloc[0]["outcome"] == "auto"

    def test_multiple_events(self, cache):
        """Insert multiple events and verify all are returned."""
        cache.log_audit_event("alice", "10.0.0.1", "view", outcome="auto")
        cache.log_audit_event("bob", "10.0.0.2", "export", outcome="approved")
        cache.log_audit_event("alice", "10.0.0.1", "delete", outcome="denied")

        df = cache.get_audit_log_df(days=1)
        assert len(df) == 3

    def test_optional_fields_can_be_none(self, cache):
        """Resource and detail can be None."""
        cache.log_audit_event(
            username="admin",
            ip_address="127.0.0.1",
            action="sync",
            resource=None,
            detail=None,
            outcome="auto",
        )
        df = cache.get_audit_log_df(days=1)
        assert len(df) == 1
        assert df.iloc[0]["resource"] is None
        assert df.iloc[0]["detail"] is None


class TestAuditLogFiltering:
    def test_filter_by_username(self, cache):
        """get_audit_log_df with username filter returns only that user's events."""
        cache.log_audit_event("alice", "10.0.0.1", "login", outcome="auto")
        cache.log_audit_event("bob", "10.0.0.2", "login", outcome="auto")
        cache.log_audit_event("alice", "10.0.0.1", "export", outcome="approved")

        df = cache.get_audit_log_df(days=1, username="alice")
        assert len(df) == 2
        assert all(df["username"] == "alice")

    def test_filter_by_username_no_results(self, cache):
        """Filtering for a non-existent user returns empty DataFrame."""
        cache.log_audit_event("alice", "10.0.0.1", "login", outcome="auto")

        df = cache.get_audit_log_df(days=1, username="nonexistent")
        assert df.empty

    def test_filter_by_days(self, cache):
        """Events older than the day window are excluded."""
        # Insert one event with current timestamp (via default)
        cache.log_audit_event("alice", "10.0.0.1", "login", outcome="auto")

        # Insert one event manually backdated to 60 days ago
        cache.conn.execute(
            "INSERT INTO audit_log (timestamp, username, ip_address, action, outcome) "
            "VALUES (datetime('now', '-60 days'), ?, ?, ?, ?)",
            ("bob", "10.0.0.2", "old_action", "auto"),
        )
        cache.conn.commit()

        # With days=30, only alice's event should appear
        df = cache.get_audit_log_df(days=30)
        assert len(df) == 1
        assert df.iloc[0]["username"] == "alice"

        # With days=90, both should appear
        df_all = cache.get_audit_log_df(days=90)
        assert len(df_all) == 2

    def test_empty_audit_log(self, cache):
        """Empty audit_log returns empty DataFrame."""
        df = cache.get_audit_log_df(days=30)
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_result_is_ordered_by_timestamp_desc(self, cache):
        """Results should be ordered by timestamp descending (newest first)."""
        cache.log_audit_event("alice", "10.0.0.1", "first", outcome="auto")
        cache.log_audit_event("alice", "10.0.0.1", "second", outcome="auto")
        cache.log_audit_event("alice", "10.0.0.1", "third", outcome="auto")

        df = cache.get_audit_log_df(days=1)
        actions = df["action"].tolist()
        # The last inserted should be first (most recent timestamp)
        assert actions[0] == "third"
        assert actions[-1] == "first"
