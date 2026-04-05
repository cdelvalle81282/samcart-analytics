"""Tests for the custom login flow in auth.py (backed by auth_db.authenticate)."""

import pytest

from auth_db import AuthDB


@pytest.fixture()
def db(tmp_path):
    """Create an AuthDB backed by a temp directory."""
    return AuthDB(db_path=str(tmp_path / "test_auth.db"))


class TestAuthLogin:
    """Verify auth_db.authenticate behaves correctly for the custom login form."""

    def test_valid_credentials_return_user(self, db):
        """authenticate() returns a user dict for correct username + password."""
        db.create_user("alice", "alice@example.com", "correct-password", "viewer")
        user = db.authenticate("alice", "correct-password")
        assert user is not None
        assert user["username"] == "alice"
        assert user["email"] == "alice@example.com"
        assert user["role"] == "viewer"
        assert user["is_active"] is True
        # password_hash must never leak into the returned dict
        assert "password_hash" not in user

    def test_wrong_password_returns_none(self, db):
        """authenticate() returns None when the password does not match."""
        db.create_user("alice", "alice@example.com", "correct-password", "viewer")
        result = db.authenticate("alice", "wrong-password")
        assert result is None

    def test_inactive_user_returns_none(self, db):
        """authenticate() returns None for a deactivated user, even with correct password."""
        db.create_user("alice", "alice@example.com", "secret", "viewer")
        db.deactivate_user("alice")
        result = db.authenticate("alice", "secret")
        assert result is None

    def test_nonexistent_user_returns_none(self, db):
        """authenticate() returns None for a username that does not exist."""
        result = db.authenticate("ghost", "any-password")
        assert result is None

    def test_admin_credentials_return_correct_role(self, db):
        """authenticate() returns the correct role for admin users."""
        db.create_user("boss", "boss@example.com", "admin-pass", "super_admin")
        user = db.authenticate("boss", "admin-pass")
        assert user is not None
        assert user["role"] == "super_admin"

    def test_authenticate_after_password_reset(self, db):
        """After reset_password(), old password fails and new password works."""
        db.create_user("alice", "alice@example.com", "old-pw", "viewer")
        db.reset_password("alice", "new-pw")
        assert db.authenticate("alice", "old-pw") is None
        assert db.authenticate("alice", "new-pw") is not None
