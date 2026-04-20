"""Authentication gate backed by AuthDB (SQLite) with migration from secrets.toml."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import streamlit as st

from auth_db import AuthDB

_SESSION_MAX_HOURS = 12

logger = logging.getLogger(__name__)

# Keys stored in session_state by the auth system
_AUTH_SESSION_KEYS = (
    "authentication_status",
    "username",
    "name",
    "permissions",
    "user_role",
)


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
        if role == "super_admin":
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


def _logout() -> None:
    """Clear all auth session state keys and rerun the app."""
    for key in _AUTH_SESSION_KEYS:
        st.session_state.pop(key, None)
    st.rerun()


def require_auth() -> None:
    """
    Check authentication status. Shows login form if not authenticated.
    Fail-closed: requires auth.db users or [auth] in secrets.toml.
    Must be called immediately after st.set_page_config().
    """
    auth_db = get_auth_db()

    # ── Already authenticated ──────────────────────────────────────────
    if st.session_state.get("authentication_status") is True:
        # Enforce absolute session expiry
        login_at_str = st.session_state.get("login_at")
        if login_at_str:
            age = datetime.utcnow() - datetime.fromisoformat(login_at_str)
            if age > timedelta(hours=_SESSION_MAX_HOURS):
                _logout()
                st.warning("Your session has expired. Please log in again.")
                st.stop()
        with st.sidebar:
            if st.button("Logout"):
                _logout()
        return

    # ── Not authenticated — show login form ────────────────────────────
    users = auth_db.list_users()
    if not users:
        st.error(
            "No users configured. Add users to auth.db or "
            "configure `[auth]` in `.streamlit/secrets.toml`."
        )
        st.stop()
        return

    st.markdown("### Login")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

    if submitted:
        user = auth_db.authenticate(username, password)
        if user is not None:
            st.session_state["authentication_status"] = True
            st.session_state["username"] = user["username"]
            st.session_state["name"] = user["username"]
            st.session_state["login_at"] = datetime.utcnow().isoformat()

            try:
                st.session_state["permissions"] = auth_db.get_permissions(user["username"])
                st.session_state["user_role"] = user["role"]
            except Exception:
                logger.exception("Failed to load permissions for %s", user["username"])
                st.session_state["permissions"] = set()
                st.session_state["user_role"] = "viewer"

            st.rerun()
        else:
            st.error("Username or password is incorrect.")

    st.stop()


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
