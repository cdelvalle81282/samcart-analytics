"""Separate SQLite database for authentication, permissions, and scheduled reports."""

import os
import sqlite3
import stat

import bcrypt

# ── Role → default permission keys ──────────────────────────────────────────

ROLE_DEFAULTS = {
    "super_admin": {
        "page:dashboard",
        "page:customer_lookup",
        "page:cohorts",
        "page:product_ltv",
        "page:daily_metrics",
        "page:revenue_forecast",
        "page:refund_analysis",
        "page:subscription_health",
        "page:customer_segments",
        "page:product_deep_dive",
        "feature:export",
        "feature:pii_access",
        "feature:sync_data",
        "feature:schedule_reports",
        "admin:manage_users",
        "admin:manage_admins",
        "admin:audit_log",
    },
    "admin": {
        "page:dashboard",
        "page:customer_lookup",
        "page:cohorts",
        "page:product_ltv",
        "page:daily_metrics",
        "page:revenue_forecast",
        "page:refund_analysis",
        "page:subscription_health",
        "page:customer_segments",
        "page:product_deep_dive",
        "feature:export",
        "feature:sync_data",
        "feature:schedule_reports",
        "admin:manage_users",
        "admin:audit_log",
    },
    "viewer": {
        "page:dashboard",
        "page:customer_lookup",
        "page:cohorts",
        "page:product_ltv",
        "page:daily_metrics",
    },
}

ALL_PERMISSIONS = sorted({p for perms in ROLE_DEFAULTS.values() for p in perms})


# ── AuthDB class ─────────────────────────────────────────────────────────────


class AuthDB:
    """Manages a separate auth.db for users, permissions, and scheduled reports."""

    def __init__(self, db_path: str = "auth.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        # Restrict DB file to owner-only (effective on Linux deployment target)
        if os.path.exists(self.db_path):
            try:
                os.chmod(self.db_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass  # Windows may not support chmod 600

    # ── Schema ───────────────────────────────────────────────────────────

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL,
                email         TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL DEFAULT 'viewer'
                              CHECK(role IN ('super_admin','admin','viewer')),
                is_active     BOOLEAN NOT NULL DEFAULT 1,
                created_by    TEXT,
                created_at    TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS permissions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                permission_key TEXT NOT NULL,
                granted        BOOLEAN NOT NULL DEFAULT 1,
                UNIQUE(user_id, permission_key)
            );

            CREATE TABLE IF NOT EXISTS scheduled_reports (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                report_type     TEXT NOT NULL,
                frequency       TEXT NOT NULL CHECK(frequency IN ('daily','weekly','monthly')),
                day_of_week     INTEGER,
                day_of_month    INTEGER,
                hour_utc        INTEGER NOT NULL DEFAULT 12,
                product_filter  TEXT,
                date_range_days INTEGER DEFAULT 30,
                spreadsheet_id  TEXT NOT NULL,
                slack_webhook   TEXT NOT NULL,
                slack_channel   TEXT,
                created_by      TEXT NOT NULL,
                is_active       BOOLEAN NOT NULL DEFAULT 1,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """
        )
        self.conn.commit()

    # ── Helpers ───────────────────────────────────────────────────────────

    def _hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def _verify_password(self, password: str, hashed: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

    def _row_to_user_dict(self, row: sqlite3.Row) -> dict:
        """Convert a Row to a user dict, excluding password_hash."""
        return {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "role": row["role"],
            "is_active": bool(row["is_active"]),
            "created_by": row["created_by"],
            "created_at": row["created_at"],
        }

    def _get_user_id(self, username: str) -> int:
        """Return user id or raise ValueError."""
        row = self.conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row is None:
            raise ValueError(f"User not found: {username}")
        return row["id"]

    # ── User CRUD ────────────────────────────────────────────────────────

    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        role: str = "viewer",
        created_by: str | None = None,
    ) -> dict:
        """Create a user with bcrypt-hashed password and role default permissions."""
        if role not in ROLE_DEFAULTS:
            raise ValueError(f"Invalid role: {role}")

        pw_hash = self._hash_password(password)
        try:
            self.conn.execute(
                "INSERT INTO users (username, email, password_hash, role, created_by) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, email, pw_hash, role, created_by),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Username already exists: {username}") from exc

        self.conn.commit()

        user = self.get_user(username)
        assert user is not None
        return user

    def get_user(self, username: str) -> dict | None:
        """Return user dict (no password_hash) or None."""
        row = self.conn.execute(
            "SELECT id, username, email, role, is_active, created_by, created_at "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_user_dict(row)

    def list_users(self) -> list[dict]:
        """Return all users (no password hashes)."""
        rows = self.conn.execute(
            "SELECT id, username, email, role, is_active, created_by, created_at "
            "FROM users ORDER BY id"
        ).fetchall()
        return [self._row_to_user_dict(r) for r in rows]

    def update_user(
        self,
        username: str,
        email: str | None = None,
        role: str | None = None,
    ) -> None:
        """Update user fields. If role changes, reset permissions to new role defaults."""
        user = self.get_user(username)
        if user is None:
            raise ValueError(f"User not found: {username}")

        if email is not None:
            self.conn.execute(
                "UPDATE users SET email = ? WHERE username = ?",
                (email, username),
            )

        if role is not None:
            if role not in ROLE_DEFAULTS:
                raise ValueError(f"Invalid role: {role}")
            self.conn.execute(
                "UPDATE users SET role = ? WHERE username = ?",
                (role, username),
            )
            # Reset permissions to new role defaults
            self.reset_permissions_to_defaults(username)

        self.conn.commit()

    def deactivate_user(self, username: str) -> None:
        """Deactivate a user. Raises ValueError if last active super_admin."""
        user = self.get_user(username)
        if user is None:
            raise ValueError(f"User not found: {username}")

        if user["role"] == "super_admin":
            count = self.conn.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'super_admin' AND is_active = 1"
            ).fetchone()[0]
            if count <= 1:
                raise ValueError("Cannot deactivate the last active super_admin")

        self.conn.execute(
            "UPDATE users SET is_active = 0 WHERE username = ?", (username,)
        )
        self.conn.commit()

    def reactivate_user(self, username: str) -> None:
        """Reactivate a deactivated user."""
        user = self.get_user(username)
        if user is None:
            raise ValueError(f"User not found: {username}")
        self.conn.execute(
            "UPDATE users SET is_active = 1 WHERE username = ?", (username,)
        )
        self.conn.commit()

    def reset_password(self, username: str, new_password: str) -> None:
        """Reset a user's password with a new bcrypt hash."""
        user = self.get_user(username)
        if user is None:
            raise ValueError(f"User not found: {username}")
        pw_hash = self._hash_password(new_password)
        self.conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (pw_hash, username),
        )
        self.conn.commit()

    def authenticate(self, username: str, password: str) -> dict | None:
        """Verify credentials. Return user dict if active and valid, else None."""
        row = self.conn.execute(
            "SELECT id, username, email, password_hash, role, is_active, "
            "created_by, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            return None
        if not row["is_active"]:
            return None
        if not self._verify_password(password, row["password_hash"]):
            return None
        return self._row_to_user_dict(row)

    # ── Permissions ──────────────────────────────────────────────────────

    def get_permissions(self, username: str) -> set[str]:
        """Get effective permissions: role defaults + overrides from permissions table."""
        user = self.get_user(username)
        if user is None:
            raise ValueError(f"User not found: {username}")

        role = user["role"]
        effective = set(ROLE_DEFAULTS.get(role, set()))
        user_id = user["id"]

        overrides = self.conn.execute(
            "SELECT permission_key, granted FROM permissions WHERE user_id = ?",
            (user_id,),
        ).fetchall()

        for row in overrides:
            if row["granted"]:
                effective.add(row["permission_key"])
            else:
                effective.discard(row["permission_key"])

        return effective

    def set_permission(self, username: str, permission_key: str, granted: bool) -> None:
        """Insert or update a permission override for a user."""
        user_id = self._get_user_id(username)
        self.conn.execute(
            "INSERT INTO permissions (user_id, permission_key, granted) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, permission_key) DO UPDATE SET granted = excluded.granted",
            (user_id, permission_key, granted),
        )
        self.conn.commit()

    def reset_permissions_to_defaults(self, username: str) -> None:
        """Delete all permission overrides for a user."""
        user_id = self._get_user_id(username)
        self.conn.execute(
            "DELETE FROM permissions WHERE user_id = ?", (user_id,)
        )
        self.conn.commit()

    def get_permission_overrides(self, username: str) -> dict[str, bool]:
        """Return just the overrides (for UI display)."""
        user_id = self._get_user_id(username)
        rows = self.conn.execute(
            "SELECT permission_key, granted FROM permissions WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        return {row["permission_key"]: bool(row["granted"]) for row in rows}

    # ── Scheduled Reports ────────────────────────────────────────────────

    def _row_to_report_dict(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "report_type": row["report_type"],
            "frequency": row["frequency"],
            "day_of_week": row["day_of_week"],
            "day_of_month": row["day_of_month"],
            "hour_utc": row["hour_utc"],
            "product_filter": row["product_filter"],
            "date_range_days": row["date_range_days"],
            "spreadsheet_id": row["spreadsheet_id"],
            "slack_webhook": row["slack_webhook"],
            "slack_channel": row["slack_channel"],
            "created_by": row["created_by"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
        }

    def create_scheduled_report(
        self,
        name: str,
        report_type: str,
        frequency: str,
        hour_utc: int,
        spreadsheet_id: str,
        slack_webhook: str,
        created_by: str,
        day_of_week: int | None = None,
        day_of_month: int | None = None,
        product_filter: str | None = None,
        date_range_days: int = 30,
        slack_channel: str | None = None,
    ) -> dict:
        """Create a scheduled report and return its dict."""
        cur = self.conn.execute(
            "INSERT INTO scheduled_reports "
            "(name, report_type, frequency, day_of_week, day_of_month, hour_utc, "
            "product_filter, date_range_days, spreadsheet_id, slack_webhook, "
            "slack_channel, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                report_type,
                frequency,
                day_of_week,
                day_of_month,
                hour_utc,
                product_filter,
                date_range_days,
                spreadsheet_id,
                slack_webhook,
                slack_channel,
                created_by,
            ),
        )
        self.conn.commit()
        return self.get_scheduled_report(cur.lastrowid)

    def list_scheduled_reports(self, active_only: bool = False) -> list[dict]:
        """List scheduled reports, optionally only active ones."""
        if active_only:
            rows = self.conn.execute(
                "SELECT * FROM scheduled_reports WHERE is_active = 1 ORDER BY id"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM scheduled_reports ORDER BY id"
            ).fetchall()
        return [self._row_to_report_dict(r) for r in rows]

    def get_scheduled_report(self, report_id: int) -> dict | None:
        """Get a single scheduled report by ID."""
        row = self.conn.execute(
            "SELECT * FROM scheduled_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_report_dict(row)

    def update_scheduled_report(self, report_id: int, **kwargs) -> None:
        """Update fields on a scheduled report. Only known columns are updated."""
        allowed_cols = {
            "name",
            "report_type",
            "frequency",
            "day_of_week",
            "day_of_month",
            "hour_utc",
            "product_filter",
            "date_range_days",
            "spreadsheet_id",
            "slack_webhook",
            "slack_channel",
            "is_active",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed_cols}
        if not updates:
            return

        set_clause = ", ".join(f"{col} = ?" for col in updates)
        values = list(updates.values()) + [report_id]
        self.conn.execute(
            f"UPDATE scheduled_reports SET {set_clause} WHERE id = ?",  # noqa: S608
            values,
        )
        self.conn.commit()

    def deactivate_scheduled_report(self, report_id: int) -> None:
        """Deactivate a scheduled report."""
        self.conn.execute(
            "UPDATE scheduled_reports SET is_active = 0 WHERE id = ?",
            (report_id,),
        )
        self.conn.commit()
