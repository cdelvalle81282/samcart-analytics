"""Tests for pii_access module: HMAC tokens, request/approve/deny lifecycle."""

import sqlite3
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# We need to mock streamlit and shared *before* importing pii_access,
# because pii_access does `import streamlit as st` and `from shared import
# get_cache` at module level. We set up module-level mocks and ensure
# pii_access is freshly imported in every test class.
# ---------------------------------------------------------------------------

TEST_HMAC_SECRET = "test_secret_key_1234567890abcdef"


def _make_test_cache():
    """Build an in-memory SamCartCache and ensure pii_access tables exist."""
    from cache import SamCartCache

    cache = SamCartCache.__new__(SamCartCache)
    cache.db_path = ":memory:"
    cache.conn = sqlite3.connect(":memory:", check_same_thread=False)
    cache.conn.execute("PRAGMA journal_mode=WAL")
    cache._init_schema()
    # Also create the pii_access_requests table
    cache.conn.execute("""
        CREATE TABLE IF NOT EXISTS pii_access_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            resource TEXT,
            requested_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','approved','denied','expired')),
            approved_by TEXT,
            token TEXT NOT NULL
        )
    """)
    cache.conn.commit()
    return cache


@pytest.fixture(autouse=True)
def _fresh_pii_module():
    """Remove pii_access from sys.modules before and after each test
    so that the module-level _tables_ensured flag is reset."""
    sys.modules.pop("pii_access", None)
    yield
    sys.modules.pop("pii_access", None)


class TestGenerateApprovalToken:
    @patch("shared.get_cache")
    @patch.dict("os.environ", {}, clear=False)
    def test_produces_sha256_hex(self, mock_get_cache):
        """generate_approval_token returns a 64-char hex string (SHA-256)."""
        mock_st = MagicMock()
        mock_st.secrets.get.return_value = TEST_HMAC_SECRET
        with patch.dict(sys.modules, {"streamlit": mock_st}):
            sys.modules.pop("pii_access", None)
            from pii_access import generate_approval_token

            token = generate_approval_token(1)
            assert isinstance(token, str)
            assert len(token) == 64
            # Must be valid hex
            int(token, 16)

    @patch("shared.get_cache")
    def test_consistent_for_same_id(self, mock_get_cache):
        """Same request_id produces the same token (deterministic HMAC)."""
        mock_st = MagicMock()
        mock_st.secrets.get.return_value = TEST_HMAC_SECRET
        with patch.dict(sys.modules, {"streamlit": mock_st}):
            sys.modules.pop("pii_access", None)
            from pii_access import generate_approval_token

            t1 = generate_approval_token(42)
            t2 = generate_approval_token(42)
            assert t1 == t2

    @patch("shared.get_cache")
    def test_different_ids_differ(self, mock_get_cache):
        """Different request_ids produce different tokens."""
        mock_st = MagicMock()
        mock_st.secrets.get.return_value = TEST_HMAC_SECRET
        with patch.dict(sys.modules, {"streamlit": mock_st}):
            sys.modules.pop("pii_access", None)
            from pii_access import generate_approval_token

            t1 = generate_approval_token(1)
            t2 = generate_approval_token(2)
            assert t1 != t2

    @patch("shared.get_cache")
    def test_raises_when_secret_missing(self, mock_get_cache):
        """generate_approval_token raises ValueError when secret is empty."""
        mock_st = MagicMock()
        mock_st.secrets.get.return_value = ""
        with patch.dict(sys.modules, {"streamlit": mock_st}):
            sys.modules.pop("pii_access", None)
            from pii_access import generate_approval_token

            with pytest.raises(ValueError, match="pii_hmac_secret"):
                generate_approval_token(1)


class TestValidateToken:
    @patch("shared.get_cache")
    def test_correct_token_validates(self, mock_get_cache):
        """validate_token returns True for a correctly generated token."""
        mock_st = MagicMock()
        mock_st.secrets.get.return_value = TEST_HMAC_SECRET
        with patch.dict(sys.modules, {"streamlit": mock_st}):
            sys.modules.pop("pii_access", None)
            from pii_access import generate_approval_token, validate_token

            token = generate_approval_token(99)
            assert validate_token(99, token) is True

    @patch("shared.get_cache")
    def test_wrong_token_rejected(self, mock_get_cache):
        """validate_token returns False for an incorrect token."""
        mock_st = MagicMock()
        mock_st.secrets.get.return_value = TEST_HMAC_SECRET
        with patch.dict(sys.modules, {"streamlit": mock_st}):
            sys.modules.pop("pii_access", None)
            from pii_access import validate_token

            assert validate_token(99, "0" * 64) is False

    @patch("shared.get_cache")
    def test_wrong_id_rejected(self, mock_get_cache):
        """Token generated for ID=1 does not validate for ID=2."""
        mock_st = MagicMock()
        mock_st.secrets.get.return_value = TEST_HMAC_SECRET
        with patch.dict(sys.modules, {"streamlit": mock_st}):
            sys.modules.pop("pii_access", None)
            from pii_access import generate_approval_token, validate_token

            token = generate_approval_token(1)
            assert validate_token(2, token) is False


class TestFullLifecycle:
    def _setup_mocks(self):
        """Set up streamlit mock and test cache, return (mock_st, cache)."""
        mock_st = MagicMock()
        mock_st.secrets.get.return_value = TEST_HMAC_SECRET
        cache = _make_test_cache()
        return mock_st, cache

    def test_request_approve_check(self):
        """Full lifecycle: request -> approve -> check returns True."""
        mock_st, cache = self._setup_mocks()

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            with patch("shared.get_cache", return_value=cache):
                sys.modules.pop("pii_access", None)
                from pii_access import (
                    approve_request,
                    check_pii_access,
                    generate_approval_token,
                    request_pii_access,
                )

                # Step 1: Request access
                rid = request_pii_access("testuser", "customer_data")
                assert isinstance(rid, int)
                assert rid >= 1

                # Step 2: Check before approval — should be False
                assert check_pii_access("testuser") is False

                # Step 3: Approve with correct token
                token = generate_approval_token(rid)
                result = approve_request(rid, token)
                assert result is True

                # Step 4: Check after approval — should be True
                assert check_pii_access("testuser") is True

    def test_deny_flow(self):
        """Request -> deny -> check returns False."""
        mock_st, cache = self._setup_mocks()

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            with patch("shared.get_cache", return_value=cache):
                sys.modules.pop("pii_access", None)
                from pii_access import (
                    check_pii_access,
                    deny_request,
                    generate_approval_token,
                    request_pii_access,
                )

                rid = request_pii_access("testuser", "customer_data")
                token = generate_approval_token(rid)

                result = deny_request(rid, token)
                assert result is True

                # After denial, access should still be False
                assert check_pii_access("testuser") is False

    def test_approve_with_wrong_token_fails(self):
        """Approving with an invalid token returns False."""
        mock_st, cache = self._setup_mocks()

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            with patch("shared.get_cache", return_value=cache):
                sys.modules.pop("pii_access", None)
                from pii_access import (
                    approve_request,
                    check_pii_access,
                    request_pii_access,
                )

                rid = request_pii_access("testuser", "customer_data")

                result = approve_request(rid, "bad_token_" + "0" * 54)
                assert result is False

                # Access should remain False
                assert check_pii_access("testuser") is False

    def test_expired_access_returns_false(self):
        """Approved access that has expired should return False."""
        mock_st, cache = self._setup_mocks()

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            with patch("shared.get_cache", return_value=cache):
                sys.modules.pop("pii_access", None)
                from pii_access import (
                    approve_request,
                    check_pii_access,
                    generate_approval_token,
                    request_pii_access,
                )

                rid = request_pii_access("testuser", "customer_data")
                token = generate_approval_token(rid)
                approve_request(rid, token)

                # Verify access is currently granted
                assert check_pii_access("testuser") is True

                # Manually set expires_at to the past
                cache.conn.execute(
                    "UPDATE pii_access_requests SET expires_at = datetime('now', '-1 hour') WHERE id = ?",
                    (rid,),
                )
                cache.conn.commit()

                # Now access should be False
                assert check_pii_access("testuser") is False

    def test_deny_with_wrong_token_fails(self):
        """Denying with an invalid token returns False, status stays pending."""
        mock_st, cache = self._setup_mocks()

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            with patch("shared.get_cache", return_value=cache):
                sys.modules.pop("pii_access", None)
                from pii_access import deny_request, request_pii_access

                rid = request_pii_access("testuser", "customer_data")

                result = deny_request(rid, "wrong_token_" + "0" * 52)
                assert result is False

                # Verify status is still pending
                row = cache.conn.execute(
                    "SELECT status FROM pii_access_requests WHERE id = ?",
                    (rid,),
                ).fetchone()
                assert row[0] == "pending"
