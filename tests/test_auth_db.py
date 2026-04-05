"""Tests for auth_db.py — users, permissions, and scheduled reports."""

import pytest

from auth_db import ALL_PERMISSIONS, ROLE_DEFAULTS, AuthDB


@pytest.fixture()
def db(tmp_path):
    """Create an AuthDB backed by a temp directory."""
    return AuthDB(db_path=str(tmp_path / "test_auth.db"))


# ── User CRUD ────────────────────────────────────────────────────────────────


class TestUserCRUD:
    def test_create_user(self, db):
        user = db.create_user("alice", "alice@example.com", "secret123", "viewer")
        assert user["username"] == "alice"
        assert user["email"] == "alice@example.com"
        assert user["role"] == "viewer"
        assert user["is_active"] is True
        assert "password_hash" not in user

    def test_create_duplicate_fails(self, db):
        db.create_user("alice", "alice@example.com", "secret123", "viewer")
        with pytest.raises(ValueError, match="Username already exists"):
            db.create_user("alice", "alice2@example.com", "other", "viewer")

    def test_get_user(self, db):
        db.create_user("bob", "bob@example.com", "pw", "admin")
        user = db.get_user("bob")
        assert user is not None
        assert user["username"] == "bob"
        assert user["role"] == "admin"
        assert "password_hash" not in user

    def test_get_user_nonexistent(self, db):
        assert db.get_user("ghost") is None

    def test_list_users(self, db):
        db.create_user("alice", "a@x.com", "pw", "viewer")
        db.create_user("bob", "b@x.com", "pw", "admin")
        users = db.list_users()
        assert len(users) == 2
        assert users[0]["username"] == "alice"
        assert users[1]["username"] == "bob"

    def test_update_user(self, db):
        db.create_user("alice", "a@x.com", "pw", "viewer")
        db.update_user("alice", email="new@x.com")
        user = db.get_user("alice")
        assert user["email"] == "new@x.com"

    def test_update_role_resets_permissions(self, db):
        db.create_user("alice", "a@x.com", "pw", "viewer")
        # Grant an extra permission override
        db.set_permission("alice", "feature:export", True)
        overrides = db.get_permission_overrides("alice")
        assert "feature:export" in overrides

        # Change role to admin — overrides should be cleared
        db.update_user("alice", role="admin")
        overrides = db.get_permission_overrides("alice")
        assert len(overrides) == 0
        assert db.get_user("alice")["role"] == "admin"

    def test_update_nonexistent_user_fails(self, db):
        with pytest.raises(ValueError, match="User not found"):
            db.update_user("ghost", email="x@x.com")

    def test_update_invalid_role_fails(self, db):
        db.create_user("alice", "a@x.com", "pw", "viewer")
        with pytest.raises(ValueError, match="Invalid role"):
            db.update_user("alice", role="root")

    def test_deactivate_user(self, db):
        db.create_user("alice", "a@x.com", "pw", "viewer")
        db.deactivate_user("alice")
        user = db.get_user("alice")
        assert user["is_active"] is False

    def test_reactivate_user(self, db):
        db.create_user("alice", "a@x.com", "pw", "viewer")
        db.deactivate_user("alice")
        db.reactivate_user("alice")
        user = db.get_user("alice")
        assert user["is_active"] is True

    def test_cannot_deactivate_last_super_admin(self, db):
        db.create_user("boss", "boss@x.com", "pw", "super_admin")
        with pytest.raises(ValueError, match="last active super_admin"):
            db.deactivate_user("boss")

    def test_can_deactivate_super_admin_if_another_exists(self, db):
        db.create_user("boss1", "b1@x.com", "pw", "super_admin")
        db.create_user("boss2", "b2@x.com", "pw", "super_admin")
        db.deactivate_user("boss1")  # should not raise
        assert db.get_user("boss1")["is_active"] is False

    def test_reset_password(self, db):
        db.create_user("alice", "a@x.com", "oldpw", "viewer")
        assert db.authenticate("alice", "oldpw") is not None
        db.reset_password("alice", "newpw")
        assert db.authenticate("alice", "oldpw") is None
        assert db.authenticate("alice", "newpw") is not None

    def test_create_user_with_created_by(self, db):
        user = db.create_user("bob", "b@x.com", "pw", "viewer", created_by="alice")
        assert user["created_by"] == "alice"

    def test_create_user_invalid_role_fails(self, db):
        with pytest.raises(ValueError, match="Invalid role"):
            db.create_user("alice", "a@x.com", "pw", "root")

    def test_slack_user_id_default_none(self, db):
        db.create_user("alice", "a@x.com", "pw", "viewer")
        user = db.get_user("alice")
        assert user["slack_user_id"] is None

    def test_update_slack_user_id(self, db):
        db.create_user("alice", "a@x.com", "pw", "viewer")
        db.update_user("alice", slack_user_id="U12345ABC")
        user = db.get_user("alice")
        assert user["slack_user_id"] == "U12345ABC"

    def test_update_slack_user_id_to_none(self, db):
        db.create_user("alice", "a@x.com", "pw", "viewer")
        db.update_user("alice", slack_user_id="U12345ABC")
        assert db.get_user("alice")["slack_user_id"] == "U12345ABC"
        db.update_user("alice", slack_user_id=None)
        assert db.get_user("alice")["slack_user_id"] is None


# ── Authentication ───────────────────────────────────────────────────────────


class TestAuthentication:
    def test_authenticate_valid(self, db):
        db.create_user("alice", "a@x.com", "secret", "viewer")
        user = db.authenticate("alice", "secret")
        assert user is not None
        assert user["username"] == "alice"
        assert "password_hash" not in user

    def test_authenticate_wrong_password(self, db):
        db.create_user("alice", "a@x.com", "secret", "viewer")
        assert db.authenticate("alice", "wrong") is None

    def test_authenticate_inactive_user(self, db):
        db.create_user("alice", "a@x.com", "secret", "viewer")
        db.deactivate_user("alice")
        assert db.authenticate("alice", "secret") is None

    def test_authenticate_nonexistent_user(self, db):
        assert db.authenticate("ghost", "pw") is None


# ── Permissions ──────────────────────────────────────────────────────────────


class TestPermissions:
    def test_default_permissions_for_viewer(self, db):
        db.create_user("alice", "a@x.com", "pw", "viewer")
        perms = db.get_permissions("alice")
        assert perms == ROLE_DEFAULTS["viewer"]

    def test_default_permissions_for_admin(self, db):
        db.create_user("bob", "b@x.com", "pw", "admin")
        perms = db.get_permissions("bob")
        assert perms == ROLE_DEFAULTS["admin"]

    def test_default_permissions_for_super_admin(self, db):
        db.create_user("boss", "boss@x.com", "pw", "super_admin")
        perms = db.get_permissions("boss")
        assert perms == ROLE_DEFAULTS["super_admin"]

    def test_grant_permission(self, db):
        db.create_user("alice", "a@x.com", "pw", "viewer")
        # Viewer doesn't have feature:export by default
        assert "feature:export" not in db.get_permissions("alice")
        db.set_permission("alice", "feature:export", True)
        assert "feature:export" in db.get_permissions("alice")

    def test_revoke_permission(self, db):
        db.create_user("alice", "a@x.com", "pw", "viewer")
        # Viewer has page:dashboard by default
        assert "page:dashboard" in db.get_permissions("alice")
        db.set_permission("alice", "page:dashboard", False)
        assert "page:dashboard" not in db.get_permissions("alice")

    def test_reset_to_defaults(self, db):
        db.create_user("alice", "a@x.com", "pw", "viewer")
        db.set_permission("alice", "feature:export", True)
        db.set_permission("alice", "page:dashboard", False)
        # After reset, should be back to viewer defaults
        db.reset_permissions_to_defaults("alice")
        perms = db.get_permissions("alice")
        assert perms == ROLE_DEFAULTS["viewer"]

    def test_get_overrides(self, db):
        db.create_user("alice", "a@x.com", "pw", "viewer")
        assert db.get_permission_overrides("alice") == {}
        db.set_permission("alice", "feature:export", True)
        db.set_permission("alice", "page:dashboard", False)
        overrides = db.get_permission_overrides("alice")
        assert overrides == {"feature:export": True, "page:dashboard": False}

    def test_get_permissions_nonexistent_user_fails(self, db):
        with pytest.raises(ValueError, match="User not found"):
            db.get_permissions("ghost")

    def test_set_permission_nonexistent_user_fails(self, db):
        with pytest.raises(ValueError, match="User not found"):
            db.set_permission("ghost", "page:dashboard", True)

    def test_all_permissions_sorted(self):
        """ALL_PERMISSIONS should be a sorted list of all unique permissions."""
        assert ALL_PERMISSIONS == sorted(ALL_PERMISSIONS)
        all_set = {p for perms in ROLE_DEFAULTS.values() for p in perms}
        assert set(ALL_PERMISSIONS) == all_set


# ── Scheduled Reports ───────────────────────────────────────────────────────


class TestScheduledReports:
    def test_create_report(self, db):
        report = db.create_scheduled_report(
            name="Weekly Revenue",
            report_type="revenue_summary",
            frequency="weekly",
            hour_utc=9,
            spreadsheet_id="sheet123",
            slack_webhook="https://hooks.slack.com/xxx",
            created_by="alice",
            day_of_week=1,
        )
        assert report["name"] == "Weekly Revenue"
        assert report["frequency"] == "weekly"
        assert report["day_of_week"] == 1
        assert report["hour_utc"] == 9
        assert report["is_active"] is True
        assert report["created_by"] == "alice"
        assert report["date_range_days"] == 30

    def test_list_active_reports(self, db):
        db.create_scheduled_report(
            name="R1", report_type="t", frequency="daily",
            hour_utc=12, spreadsheet_id="s1", slack_webhook="w1", created_by="alice",
        )
        r2 = db.create_scheduled_report(
            name="R2", report_type="t", frequency="weekly",
            hour_utc=12, spreadsheet_id="s2", slack_webhook="w2", created_by="bob",
        )
        db.deactivate_scheduled_report(r2["id"])

        all_reports = db.list_scheduled_reports(active_only=False)
        assert len(all_reports) == 2

        active_reports = db.list_scheduled_reports(active_only=True)
        assert len(active_reports) == 1
        assert active_reports[0]["name"] == "R1"

    def test_deactivate_report(self, db):
        report = db.create_scheduled_report(
            name="R1", report_type="t", frequency="daily",
            hour_utc=12, spreadsheet_id="s1", slack_webhook="w1", created_by="alice",
        )
        db.deactivate_scheduled_report(report["id"])
        updated = db.get_scheduled_report(report["id"])
        assert updated["is_active"] is False

    def test_update_report(self, db):
        report = db.create_scheduled_report(
            name="R1", report_type="t", frequency="daily",
            hour_utc=12, spreadsheet_id="s1", slack_webhook="w1", created_by="alice",
        )
        db.update_scheduled_report(report["id"], name="Updated", hour_utc=15)
        updated = db.get_scheduled_report(report["id"])
        assert updated["name"] == "Updated"
        assert updated["hour_utc"] == 15

    def test_get_report(self, db):
        report = db.create_scheduled_report(
            name="R1", report_type="t", frequency="monthly",
            hour_utc=6, spreadsheet_id="s1", slack_webhook="w1", created_by="bob",
            day_of_month=15, product_filter="prod_123", date_range_days=60,
            slack_channel="#reports",
        )
        fetched = db.get_scheduled_report(report["id"])
        assert fetched["name"] == "R1"
        assert fetched["frequency"] == "monthly"
        assert fetched["day_of_month"] == 15
        assert fetched["product_filter"] == "prod_123"
        assert fetched["date_range_days"] == 60
        assert fetched["slack_channel"] == "#reports"

    def test_get_nonexistent_report(self, db):
        assert db.get_scheduled_report(999) is None

    def test_update_ignores_unknown_columns(self, db):
        report = db.create_scheduled_report(
            name="R1", report_type="t", frequency="daily",
            hour_utc=12, spreadsheet_id="s1", slack_webhook="w1", created_by="alice",
        )
        # Should not raise — unknown keys are silently ignored
        db.update_scheduled_report(report["id"], bogus_col="value")
        fetched = db.get_scheduled_report(report["id"])
        assert fetched["name"] == "R1"  # unchanged
