"""Authentication gate backed by AuthDB (SQLite) with migration from secrets.toml."""

from __future__ import annotations

import logging

import streamlit as st
import streamlit_authenticator as stauth

from auth_db import AuthDB

logger = logging.getLogger(__name__)


# ── Singleton ─────────────────────────────────────────────────────────────────


@st.cache_resource
def get_auth_db() -> AuthDB:
    """Return the shared AuthDB instance (creates auth.db on first call)."""
    db = AuthDB()
    _migrate_from_secrets(db)
    return db


def _migrate_from_secrets(db: AuthDB) -> None:
    """One-time migration: copy users from secrets.toml into auth.db if empty."""
    if db.list_users():
        return  # already populated

    try:
        creds = st.secrets["auth"]["credentials"]["usernames"]
    except (KeyError, FileNotFoundError):
        return  # no secrets to migrate

    for username, user_data in creds.items():
        role = user_data.get("role", "viewer")
        # Map old roles to new system
        if role in ("admin", "super_admin"):
            db_role = "super_admin"
        elif role == "admin":
            db_role = "admin"
        else:
            db_role = "viewer"

        # The password in secrets.toml is already bcrypt-hashed.
        # We write it directly to avoid double-hashing.
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


# ── Auth Gate ─────────────────────────────────────────────────────────────────


def require_auth() -> None:
    """
    Check authentication status. Shows login form if not authenticated.
    Fail-closed: requires either auth.db users or [auth] in secrets.toml.
    Must be called immediately after st.set_page_config().
    """
    auth_db = get_auth_db()

    # Build credentials dict from auth.db
    users = auth_db.list_users()
    if not users:
        st.error(
            "No users configured. Add users to auth.db or "
            "configure `[auth]` in `.streamlit/secrets.toml`."
        )
        st.stop()
        return

    credentials: dict = {"usernames": {}}
    for user in users:
        if not user["is_active"]:
            continue
        # Fetch raw password hash from DB for streamlit-authenticator
        row = auth_db.conn.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (user["username"],),
        ).fetchone()
        if row is None:
            continue
        credentials["usernames"][user["username"]] = {
            "email": user["email"],
            "name": user["username"],
            "password": row["password_hash"],
        }

    # Cookie config from secrets (still needed for cookie encryption)
    try:
        auth_config = st.secrets["auth"]
        cookie_key = auth_config.get("cookie_key", "")
    except (KeyError, FileNotFoundError):
        cookie_key = ""

    if not cookie_key:
        st.error("Set `cookie_key` in `[auth]` section of `.streamlit/secrets.toml`.")
        st.stop()
        return

    auth_config = st.secrets.get("auth", {})
    authenticator = stauth.Authenticate(
        credentials=credentials,
        cookie_name=auth_config.get("cookie_name", "samcart_analytics"),
        cookie_key=cookie_key,
        cookie_expiry_days=auth_config.get("cookie_expiry_days", 7),
    )

    authenticator.login()

    if st.session_state.get("authentication_status") is None:
        st.warning("Please enter your username and password.")
        st.stop()
    elif st.session_state.get("authentication_status") is False:
        st.error("Username or password is incorrect.")
        st.stop()

    # Authenticated — render logout in sidebar
    authenticator.logout("Logout", "sidebar")

    # Load permissions into session state
    username = st.session_state.get("username", "")
    if username and "permissions" not in st.session_state:
        try:
            st.session_state["permissions"] = auth_db.get_permissions(username)
            user = auth_db.get_user(username)
            if user:
                st.session_state["user_role"] = user["role"]
        except Exception:
            logger.exception("Failed to load permissions for %s", username)
            st.session_state["permissions"] = set()
            st.session_state["user_role"] = "viewer"


# ── Permission Helpers ────────────────────────────────────────────────────────


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
