"""PII access control module with HMAC token-based approval flow.

Provides time-limited PII access requests that require HMAC-validated
approval before granting access. Tokens are generated using a shared
secret stored in secrets.toml.
"""

import hashlib
import hmac

import streamlit as st

from shared import get_cache


# ------------------------------------------------------------------
# Table initialisation (lazy, idempotent)
# ------------------------------------------------------------------

_tables_ensured = False


def _ensure_pii_tables(conn):
    """Create the pii_access_requests table if it does not exist."""
    global _tables_ensured  # noqa: PLW0603
    if _tables_ensured:
        return
    conn.execute("""
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
    conn.commit()
    _tables_ensured = True


# ------------------------------------------------------------------
# HMAC helpers
# ------------------------------------------------------------------

def _get_hmac_secret() -> str:
    """Return the PII HMAC secret from secrets.toml."""
    return st.secrets.get("pii_hmac_secret", "")


def generate_approval_token(request_id: int) -> str:
    """Generate an HMAC-SHA256 approval token for a given request ID.

    Raises ``ValueError`` if ``pii_hmac_secret`` is not configured.
    """
    secret = _get_hmac_secret()
    if not secret:
        raise ValueError("pii_hmac_secret must be set in secrets.toml")
    return hmac.new(
        secret.encode(), str(request_id).encode(), hashlib.sha256
    ).hexdigest()


def validate_token(request_id: int, token: str) -> bool:
    """Validate *token* against the expected HMAC for *request_id*.

    Uses constant-time comparison to prevent timing attacks.
    """
    expected = generate_approval_token(request_id)
    return hmac.compare_digest(expected, token)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def request_pii_access(username: str, resource: str | None = None) -> int:
    """Create a new PII access request and return its ID.

    The request starts with status ``pending`` and includes an HMAC token
    that must be presented when approving or denying the request.
    """
    cache = get_cache()
    _ensure_pii_tables(cache.conn)

    # Insert a placeholder row first so we can get the auto-incremented ID
    cur = cache.conn.execute(
        "INSERT INTO pii_access_requests (username, resource, token) VALUES (?, ?, '')",
        (username, resource),
    )
    request_id = cur.lastrowid

    # Generate the HMAC token using the real ID and update the row
    token = generate_approval_token(request_id)
    cache.conn.execute(
        "UPDATE pii_access_requests SET token = ? WHERE id = ?",
        (token, request_id),
    )
    cache.conn.commit()
    return request_id


def check_pii_access(username: str) -> bool:
    """Return ``True`` if *username* has an unexpired, approved PII access grant."""
    cache = get_cache()
    _ensure_pii_tables(cache.conn)
    row = cache.conn.execute(
        "SELECT id FROM pii_access_requests "
        "WHERE username = ? AND status = 'approved' AND expires_at > datetime('now')",
        (username,),
    ).fetchone()
    return row is not None


def approve_request(request_id: int, token: str) -> bool:
    """Approve a pending PII access request.

    Returns ``True`` on success. Returns ``False`` if the token is invalid
    or the request is not in ``pending`` status.
    """
    if not validate_token(request_id, token):
        return False
    cache = get_cache()
    _ensure_pii_tables(cache.conn)
    cur = cache.conn.execute(
        "UPDATE pii_access_requests "
        "SET status = 'approved', expires_at = datetime('now', '+30 minutes') "
        "WHERE id = ? AND status = 'pending'",
        (request_id,),
    )
    cache.conn.commit()
    return cur.rowcount > 0


def deny_request(request_id: int, token: str) -> bool:
    """Deny a pending PII access request.

    Returns ``True`` on success. Returns ``False`` if the token is invalid
    or the request is not in ``pending`` status.
    """
    if not validate_token(request_id, token):
        return False
    cache = get_cache()
    _ensure_pii_tables(cache.conn)
    cur = cache.conn.execute(
        "UPDATE pii_access_requests SET status = 'denied' "
        "WHERE id = ? AND status = 'pending'",
        (request_id,),
    )
    cache.conn.commit()
    return cur.rowcount > 0
