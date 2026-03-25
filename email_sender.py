"""Gmail SMTP email sender for PII approval requests and reports."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import streamlit as st

logger = logging.getLogger(__name__)


def _get_email_config():
    """Read email config from secrets.toml."""
    cfg = st.secrets.get("email", {})
    return {
        "smtp_server": cfg.get("smtp_server", "smtp.gmail.com"),
        "smtp_port": int(cfg.get("smtp_port", 587)),
        "sender_email": cfg.get("sender_email", ""),
        "app_password": cfg.get("app_password", ""),
        "admin_email": cfg.get("admin_email", ""),
    }


def _get_base_url():
    """Get the app base URL from secrets."""
    return st.secrets.get("app_base_url", "https://opisamcart.duckdns.org")


def send_approval_email(
    to_admin_email, requester_username, resource, request_id, token
):
    """Send PII access approval request email with approve/deny links."""
    cfg = _get_email_config()
    if not cfg["sender_email"] or not cfg["app_password"]:
        logger.error("Email not configured in secrets.toml")
        return False

    base_url = _get_base_url()
    approve_url = (
        f"{base_url}/PII_Approval?action=approve&rid={request_id}&token={token}"
    )
    deny_url = (
        f"{base_url}/PII_Approval?action=deny&rid={request_id}&token={token}"
    )

    subject = f"PII Access Request from {requester_username}"
    html = f"""\
    <html><body>
    <h2>PII Access Request</h2>
    <p><strong>User:</strong> {requester_username}</p>
    <p><strong>Resource:</strong> {resource}</p>
    <p>Click below to approve or deny this request. \
Approval grants 30 minutes of PII access.</p>
    <p>
        <a href="{approve_url}" \
style="background-color:#28a745;color:white;padding:12px 24px;\
text-decoration:none;border-radius:4px;margin-right:12px;">Approve</a>
        <a href="{deny_url}" \
style="background-color:#dc3545;color:white;padding:12px 24px;\
text-decoration:none;border-radius:4px;">Deny</a>
    </p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["sender_email"]
    msg["To"] = to_admin_email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"]) as server:
            server.starttls()
            server.login(cfg["sender_email"], cfg["app_password"])
            server.sendmail(cfg["sender_email"], to_admin_email, msg.as_string())
        logger.info(
            "Approval email sent to %s for user %s",
            to_admin_email,
            requester_username,
        )
        return True
    except Exception:
        logger.exception("Failed to send approval email")
        return False


def send_report_email(to_email, subject, html_body):
    """Send a report email. Returns True on success."""
    cfg = _get_email_config()
    if not cfg["sender_email"] or not cfg["app_password"]:
        logger.error("Email not configured in secrets.toml")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["sender_email"]
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"]) as server:
            server.starttls()
            server.login(cfg["sender_email"], cfg["app_password"])
            server.sendmail(cfg["sender_email"], to_email, msg.as_string())
        logger.info("Report email sent to %s: %s", to_email, subject)
        return True
    except Exception:
        logger.exception("Failed to send report email")
        return False
