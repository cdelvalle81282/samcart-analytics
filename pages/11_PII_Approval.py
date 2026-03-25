"""PII Access Approval handler -- processes approve/deny links from email."""

# NOTE: This page intentionally has NO require_auth() call.
# It is accessed via email links by admins who may not be logged in.
# Security is provided by HMAC-SHA256 token validation — without a valid
# token, no action can be taken. This is a deliberate design tradeoff
# for usability (one-click approve/deny from email).

import streamlit as st

from pii_access import approve_request, deny_request, validate_token
from shared import get_cache

st.set_page_config(page_title="PII Approval", page_icon=":shield:", layout="centered")

st.title("PII Access Approval")

# Read query params
params = st.query_params
action = params.get("action", "")
rid = params.get("rid", "")
token = params.get("token", "")

if not action or not rid or not token:
    st.warning("Missing parameters. Use the link from your approval email.")
    st.stop()

# Validate token first
try:
    rid_int = int(rid)
except ValueError:
    st.error("Invalid request ID.")
    st.stop()

if not validate_token(rid_int, token):
    st.error("Invalid or expired link. The token does not match.")
    st.stop()

cache = get_cache()

if action == "approve":
    success = approve_request(rid_int, token)
    if success:
        cache.log_audit_event(
            username="admin_via_email",
            ip_address="email_link",
            action="pii_approve",
            resource=f"request_{rid}",
            detail="Approved via email link",
            outcome="approved",
        )
        st.success("Access granted! The requester now has 30 minutes of PII access.")
    else:
        st.warning("Request was already processed or has expired.")
elif action == "deny":
    success = deny_request(rid_int, token)
    if success:
        cache.log_audit_event(
            username="admin_via_email",
            ip_address="email_link",
            action="pii_deny",
            resource=f"request_{rid}",
            detail="Denied via email link",
            outcome="denied",
        )
        st.error("Request denied. The requester will not receive PII access.")
    else:
        st.warning("Request was already processed or has expired.")
else:
    st.error("Invalid action. Expected 'approve' or 'deny'.")
