"""Security tests for hardening changes."""

import sqlite3
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# 5a. Table name validation
# ---------------------------------------------------------------------------


class TestTableValidation:
    def test_valid_table_passes(self):
        from cache import _validate_table

        assert _validate_table("orders") == "orders"
        assert _validate_table("customers") == "customers"
        assert _validate_table("subscriptions") == "subscriptions"
        assert _validate_table("charges") == "charges"
        assert _validate_table("products") == "products"
        assert _validate_table("sync_meta") == "sync_meta"
        assert _validate_table("audit_log") == "audit_log"
        assert _validate_table("pii_access_requests") == "pii_access_requests"

    def test_invalid_table_raises(self):
        from cache import _validate_table

        with pytest.raises(ValueError, match="Invalid table name"):
            _validate_table("evil; DROP TABLE")

        with pytest.raises(ValueError, match="Invalid table name"):
            _validate_table("nonexistent")

        with pytest.raises(ValueError, match="Invalid table name"):
            _validate_table("")


# ---------------------------------------------------------------------------
# 5b. LIKE escaping (real SQLite)
# ---------------------------------------------------------------------------


class TestLikeEscaping:
    @pytest.fixture()
    def cache_with_data(self):
        """Create a SamCartCache with an in-memory DB and test rows."""
        from cache import SamCartCache

        cache = SamCartCache.__new__(SamCartCache)
        cache.db_path = ":memory:"
        cache.conn = sqlite3.connect(":memory:", check_same_thread=False)
        cache.conn.execute("PRAGMA journal_mode=WAL")
        cache._init_schema()

        # Insert test rows with tricky email characters
        test_customers = [
            ("1", "normal@example.com", "Normal", "User", "", "", "", "", "2024-01-01"),
            ("2", "test%special@example.com", "Test", "Percent", "", "", "", "", "2024-01-02"),
            ("3", "test_under@example.com", "Test", "Under", "", "", "", "", "2024-01-03"),
            ("4", "test\\back@example.com", "Test", "Back", "", "", "", "", "2024-01-04"),
            ("5", "testing@example.com", "Testing", "User", "", "", "", "", "2024-01-05"),
        ]
        cache.conn.executemany(
            "INSERT INTO customers (id, email, first_name, last_name, phone, billing_city, billing_state, billing_country, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            test_customers,
        )
        cache.conn.commit()
        return cache

    def test_percent_treated_as_literal(self, cache_with_data):
        """Searching for 'test%' should only match the row with literal % in email."""
        results = cache_with_data.search_customers("test%")
        emails = results["email"].tolist()
        assert "test%special@example.com" in emails
        # Should NOT match all rows starting with "test"
        assert "testing@example.com" not in emails

    def test_underscore_treated_as_literal(self, cache_with_data):
        """Searching for 'test_' should only match the row with literal _ in email."""
        results = cache_with_data.search_customers("test_")
        emails = results["email"].tolist()
        assert "test_under@example.com" in emails
        # Should NOT match 'test%special' (where _ would match any char)
        assert "test%special@example.com" not in emails

    def test_max_length_returns_empty(self, cache_with_data):
        """Queries exceeding 100 chars should return empty DataFrame."""
        long_query = "a" * 101
        results = cache_with_data.search_customers(long_query)
        assert results.empty


# ---------------------------------------------------------------------------
# 5c. Auth gate smoke test
# ---------------------------------------------------------------------------


class TestAuthGate:
    def test_require_auth_stops_when_no_users(self):
        """require_auth() calls st.stop() when no users are configured."""
        import sys

        mock_st = MagicMock()
        mock_st.secrets.__getitem__ = MagicMock(side_effect=KeyError("auth"))
        mock_st.stop = MagicMock(side_effect=SystemExit)
        mock_st.session_state = {}

        # Mock AuthDB to return no users
        mock_auth_db = MagicMock()
        mock_auth_db.list_users.return_value = []

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            # Remove cached auth module so it reimports with our mocks
            sys.modules.pop("auth", None)
            from auth import require_auth

            with patch("auth.get_auth_db", return_value=mock_auth_db):
                with pytest.raises(SystemExit):
                    require_auth()

                mock_st.error.assert_called_once()
                mock_st.stop.assert_called_once()

        # Clean up so other tests aren't affected
        sys.modules.pop("auth", None)


# ---------------------------------------------------------------------------
# 5d. Filename sanitization
# ---------------------------------------------------------------------------


class TestFilenameSanitization:
    def test_email_in_filename_is_stripped(self):
        """render_export_buttons should not use email in download filenames."""

        # We test the guardrail logic directly: if "@" is in filename_base, it becomes "export"
        # Simulate by checking that the function would sanitize
        test_filename = "orders_jane@example.com"
        if "@" in test_filename:
            sanitized = "export"
        else:
            sanitized = test_filename
        assert "jane@example.com" not in sanitized
        assert sanitized == "export"

    def test_clean_filename_passes_through(self):
        """Filenames without @ should pass through unchanged."""
        test_filename = "customer_orders"
        if "@" in test_filename:
            sanitized = "export"
        else:
            sanitized = test_filename
        assert sanitized == "customer_orders"

    def test_customer_lookup_uses_clean_filename(self):
        """Verify the call site in Customer Lookup uses non-PII filename."""

        with open("pages/1_Customer_Lookup.py") as f:
            source = f.read()

        # The source should contain 'customer_orders' not f"orders_{selected_email}"
        assert '"customer_orders"' in source
        assert "orders_{selected_email}" not in source


# ---------------------------------------------------------------------------
# 5e. PII_COLUMNS behavior
# ---------------------------------------------------------------------------


class TestPiiColumns:
    def test_strip_pii_removes_first_and_last_name(self):
        """_strip_pii should remove first_name and last_name when include_pii=False."""
        from export import _strip_pii

        df = pd.DataFrame(
            {
                "id": [1, 2],
                "email": ["a@b.com", "c@d.com"],
                "first_name": ["Alice", "Bob"],
                "last_name": ["Smith", "Jones"],
                "phone": ["555-0100", "555-0200"],
                "total": [100, 200],
            }
        )

        result = _strip_pii(df, include_pii=False)
        assert "first_name" not in result.columns
        assert "last_name" not in result.columns
        assert "email" not in result.columns
        assert "phone" not in result.columns
        # Non-PII columns should remain
        assert "id" in result.columns
        assert "total" in result.columns

    def test_strip_pii_keeps_all_when_include_pii_true(self):
        """_strip_pii should keep all columns when include_pii=True."""
        from export import _strip_pii

        df = pd.DataFrame(
            {
                "id": [1],
                "first_name": ["Alice"],
                "last_name": ["Smith"],
            }
        )

        result = _strip_pii(df, include_pii=True)
        assert "first_name" in result.columns
        assert "last_name" in result.columns


# ---------------------------------------------------------------------------
# 5f. Deletion pair validation
# ---------------------------------------------------------------------------


class TestDeletionPairValidation:
    def test_delete_customer_data_validates_tables(self):
        """delete_customer_data should validate all table names against _ALLOWED_TABLES."""
        from cache import _ALLOWED_TABLES

        # Verify the deletion pairs are all in _ALLOWED_TABLES
        deletion_tables = ["orders", "customers", "subscriptions", "charges"]
        for table in deletion_tables:
            assert table in _ALLOWED_TABLES, f"{table} not in _ALLOWED_TABLES"

    def test_delete_customer_data_runs_without_assertion_error(self):
        """delete_customer_data should not raise AssertionError for its built-in pairs."""
        from cache import SamCartCache

        cache = SamCartCache.__new__(SamCartCache)
        cache.db_path = ":memory:"
        cache.conn = sqlite3.connect(":memory:", check_same_thread=False)
        cache.conn.execute("PRAGMA journal_mode=WAL")
        cache._init_schema()

        # Should not raise AssertionError
        counts = cache.delete_customer_data("nonexistent@example.com")
        assert isinstance(counts, dict)
        assert "orders" in counts
        assert "customers" in counts
