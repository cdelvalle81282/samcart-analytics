"""Tests for cache.py schema migration, charge re-upsert, and sync behavior."""

import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from cache import SamCartCache


@pytest.fixture
def cache_db_path():
    """Create a workspace-local SQLite path that the sandbox allows."""
    fd, path = tempfile.mkstemp(prefix="cache_test_", suffix=".db", dir=".")
    os.close(fd)
    try:
        yield path
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture
def fresh_cache(cache_db_path):
    """Create a fresh SamCartCache in a temp database file."""
    cache = SamCartCache(cache_db_path)
    try:
        yield cache
    finally:
        cache.conn.close()


@pytest.fixture
def legacy_cache(cache_db_path):
    """Create a cache with the OLD schema (no new columns)."""
    conn = sqlite3.connect(cache_db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY, customer_email TEXT, customer_id TEXT,
            product_id TEXT, product_name TEXT, total REAL, created_at TEXT,
            subscription_id TEXT
        );
        CREATE TABLE IF NOT EXISTS customers (
            id TEXT PRIMARY KEY, email TEXT NOT NULL, first_name TEXT,
            last_name TEXT, phone TEXT, billing_city TEXT, billing_state TEXT,
            billing_country TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS subscriptions (
            id TEXT PRIMARY KEY, customer_email TEXT, product_id TEXT,
            product_name TEXT, status TEXT, interval TEXT, price REAL,
            created_at TEXT, canceled_at TEXT
        );
        CREATE TABLE IF NOT EXISTS charges (
            id TEXT PRIMARY KEY, order_id TEXT, subscription_id TEXT,
            customer_email TEXT, amount REAL, status TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY, name TEXT, price REAL, sku TEXT
        );
        CREATE TABLE IF NOT EXISTS sync_meta (
            table_name TEXT PRIMARY KEY, last_synced_at TEXT, record_count INTEGER
        );
    """)
    conn.commit()
    conn.close()
    cache = SamCartCache(cache_db_path)
    try:
        yield cache
    finally:
        cache.conn.close()


def _get_columns(conn, table):
    """Get column names for a table."""
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


class TestFreshDB:
    """Verify all columns exist after fresh init."""

    def test_subscriptions_has_new_columns(self, fresh_cache):
        cols = _get_columns(fresh_cache.conn, "subscriptions")
        assert "trial_days" in cols
        assert "next_bill_date" in cols
        assert "billing_cycle_count" in cols

    def test_charges_has_new_columns(self, fresh_cache):
        cols = _get_columns(fresh_cache.conn, "charges")
        assert "refund_amount" in cols
        assert "refund_date" in cols


class TestMigration:
    """Verify _migrate_schema() adds columns to existing DB."""

    def test_migration_adds_missing_columns(self, legacy_cache):
        # After constructing SamCartCache on the legacy DB, migration should have run
        sub_cols = _get_columns(legacy_cache.conn, "subscriptions")
        assert "trial_days" in sub_cols
        assert "next_bill_date" in sub_cols
        assert "billing_cycle_count" in sub_cols

        charge_cols = _get_columns(legacy_cache.conn, "charges")
        assert "refund_amount" in charge_cols
        assert "refund_date" in charge_cols

    def test_migration_is_idempotent(self, legacy_cache):
        """Second call to _migrate_schema() should be a no-op."""
        # First migration happened in __init__
        legacy_cache._migrate_schema()  # Second call — should not raise
        sub_cols = _get_columns(legacy_cache.conn, "subscriptions")
        assert "trial_days" in sub_cols
        assert "next_bill_date" in sub_cols
        assert "billing_cycle_count" in sub_cols


class TestChargeReUpsert:
    """Charge synced without refund, then re-synced with refund metadata."""

    def test_charge_updates_with_refund_fields(self, fresh_cache):
        # First sync: charge without refund
        charge_v1 = {
            "id": "ch_001",
            "order_id": "ord_001",
            "subscription_rebill_id": "sub_001",
            "customer_id": "cust_001",
            "total": 5000,  # $50.00 in cents
            "charge_refund_status": "",
            "created_at": "2024-01-15T10:00:00Z",
            "refund_amount": 0,
            "refund_date": None,
        }
        fresh_cache._upsert_charges([charge_v1])
        fresh_cache.conn.commit()

        row = fresh_cache.conn.execute(
            "SELECT amount, status, refund_amount, refund_date FROM charges WHERE id = ?",
            ("ch_001",),
        ).fetchone()
        assert row[0] == 50.0  # $50
        assert row[1] == ""
        assert row[2] == 0.0
        assert row[3] is None

        # Second sync: same charge now refunded
        charge_v2 = {
            "id": "ch_001",
            "order_id": "ord_001",
            "subscription_rebill_id": "sub_001",
            "customer_id": "cust_001",
            "total": 5000,
            "charge_refund_status": "partially_refunded",
            "created_at": "2024-01-15T10:00:00Z",
            "refund_amount": 2500,  # $25 refund in cents
            "refund_date": "2024-02-10T12:00:00Z",
        }
        fresh_cache._upsert_charges([charge_v2])
        fresh_cache.conn.commit()

        row = fresh_cache.conn.execute(
            "SELECT amount, status, refund_amount, refund_date FROM charges WHERE id = ?",
            ("ch_001",),
        ).fetchone()
        assert row[0] == 50.0  # amount unchanged
        assert row[1] == "partially_refunded"
        assert row[2] == 25.0  # $25 refund
        assert row[3] is not None  # refund_date populated


class TestSyncBehavior:
    """Verify charges are full-synced even when force_full=False."""

    def test_charges_full_synced_in_default_mode(self, fresh_cache):
        """Mock _sync_table, call sync_all(force_full=False), check charges uses force_full=True."""
        mock_client = MagicMock()
        mock_client.get_products.return_value = []
        mock_client.get_customers.return_value = []
        mock_client.get_subscriptions.return_value = []
        mock_client.get_charges.return_value = []
        mock_client.get_orders.return_value = []

        calls = []
        original_sync_table = fresh_cache._sync_table

        def spy_sync_table(table_name, *args, **kwargs):
            calls.append((table_name, kwargs.get("force_full", False)))
            return original_sync_table(table_name, *args, **kwargs)

        with patch.object(fresh_cache, "_sync_table", side_effect=spy_sync_table):
            fresh_cache.sync_all(mock_client, force_full=False, headless=True)

        # Find the charges call
        charge_calls = [(t, ff) for t, ff in calls if t == "charges"]
        assert len(charge_calls) == 1
        assert charge_calls[0][1] is True, "charges should use force_full=True"

        # Orders should NOT be force_full when force_full=False
        order_calls = [(t, ff) for t, ff in calls if t == "orders"]
        assert len(order_calls) == 1
        assert order_calls[0][1] is False, "orders should use force_full=False in default mode"

    def test_failed_full_sync_preserves_existing_charges(self, fresh_cache):
        """A failed full sync should roll back and keep prior cached data intact."""
        fresh_cache.conn.execute(
            """INSERT INTO charges
               (id, order_id, subscription_id, customer_email, amount, status, created_at, refund_amount, refund_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("ch_existing", "ord_1", "", "user@example.com", 42.0, "", "2024-01-01T00:00:00Z", 0.0, None),
        )
        fresh_cache.conn.commit()

        mock_client = MagicMock()
        mock_client.get_products.return_value = []
        mock_client.get_customers.return_value = []
        mock_client.get_subscriptions.return_value = []
        mock_client.get_charges.side_effect = RuntimeError("boom")
        mock_client.get_orders.return_value = []

        with pytest.raises(RuntimeError, match="boom"):
            fresh_cache.sync_all(mock_client, force_full=False, headless=True)

        row = fresh_cache.conn.execute(
            "SELECT id, amount FROM charges WHERE id = ?",
            ("ch_existing",),
        ).fetchone()
        assert row == ("ch_existing", 42.0)


class TestSyncSafety:
    """Verify that force_full does not wipe data on API failure."""

    def test_api_failure_preserves_existing_data(self, fresh_cache):
        """If fetcher raises, existing data in the table should survive."""
        # Pre-populate charges
        fresh_cache._upsert_charges([{
            "id": "ch_existing",
            "order_id": "ord_001",
            "subscription_rebill_id": "",
            "customer_id": "cust_001",
            "total": 5000,
            "charge_refund_status": "",
            "created_at": "2024-01-15T10:00:00Z",
            "refund_amount": 0,
            "refund_date": None,
        }])
        fresh_cache.conn.commit()

        count_before = fresh_cache.conn.execute("SELECT COUNT(*) FROM charges").fetchone()[0]
        assert count_before == 1

        # Simulate API failure
        def failing_fetcher(**kwargs):
            raise ConnectionError("API down")

        with pytest.raises(ConnectionError):
            fresh_cache._sync_table(
                "charges", failing_fetcher, fresh_cache._upsert_charges,
                force_full=True, headless=True,
            )

        # Data should still be there
        count_after = fresh_cache.conn.execute("SELECT COUNT(*) FROM charges").fetchone()[0]
        assert count_after == 1, "Existing charge data should survive an API failure"
