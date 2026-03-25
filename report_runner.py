"""Headless report runner for cron -- sends scheduled reports via Email/Slack."""

import logging
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
import requests

from analytics import build_daily_summary
from cache import SamCartCache

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def _load_secrets() -> dict:
    """Load secrets.toml using tomllib (no Streamlit dependency)."""
    secrets_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".streamlit", "secrets.toml"
    )
    try:
        import tomllib

        with open(secrets_path, "rb") as f:
            return tomllib.load(f)
    except (FileNotFoundError, ImportError):
        return {}


def _is_report_due(frequency: str) -> bool:
    """Check if a report with given frequency should run today."""
    now = datetime.now(timezone.utc)
    if frequency == "daily":
        return True
    if frequency == "weekly":
        return now.weekday() == 0  # Monday
    if frequency == "monthly":
        return now.day == 1  # First of month
    return False


def _format_html_report(
    name: str, df: pd.DataFrame, products: list[str] | None = None
) -> str:
    """Format a DataFrame as an HTML report table."""
    data = df.copy()
    if products and "product_name" in data.columns:
        data = data[data["product_name"].isin(products)]
    if data.empty:
        return f"<h2>{name}</h2><p>No data available.</p>"

    html = f"<h2>{name}</h2>\n"
    html += (
        "<table border='1' cellpadding='8' cellspacing='0'"
        " style='border-collapse:collapse;'>\n"
    )
    html += "<tr>"
    for col in data.columns:
        html += f"<th style='background:#f0f0f0;'>{col}</th>"
    html += "</tr>\n"
    for _, row in data.iterrows():
        html += "<tr>"
        for col in data.columns:
            val = row[col]
            if isinstance(val, float):
                html += f"<td>${val:,.2f}</td>"
            else:
                html += f"<td>{val}</td>"
        html += "</tr>\n"
    html += "</table>"
    return html


def _send_email(
    secrets: dict, to_email: str, subject: str, html_body: str
) -> bool:
    """Send HTML email via SMTP using config from secrets.toml."""
    cfg = secrets.get("email", {})
    sender = cfg.get("sender_email", "")
    password = cfg.get("app_password", "")
    if not sender or not password:
        logger.error("Email not configured in secrets.toml")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(
            cfg.get("smtp_server", "smtp.gmail.com"),
            int(cfg.get("smtp_port", 587)),
        ) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, to_email, msg.as_string())
        logger.info("Email sent to %s: %s", to_email, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        return False


def _send_slack(
    webhook_url: str,
    name: str,
    df: pd.DataFrame,
    products: list[str] | None = None,
) -> bool:
    """Send report to Slack via incoming webhook."""
    if not webhook_url:
        logger.error("Slack webhook URL not configured")
        return False

    data = df.copy()
    if products and "product_name" in data.columns:
        data = data[data["product_name"].isin(products)]

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": name}},
        {"type": "divider"},
    ]

    if data.empty:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "No data available."},
            }
        )
    else:
        lines = []
        for _, row in data.head(20).iterrows():
            parts = []
            for col in data.columns:
                val = row[col]
                if isinstance(val, float):
                    parts.append(f"*{col}:* ${val:,.2f}")
                else:
                    parts.append(f"*{col}:* {val}")
            lines.append(" | ".join(parts))

        # Slack has a 3000 char limit per text block
        text = "\n".join(lines)
        if len(text) > 2900:
            text = text[:2900] + "\n..."

        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": text}}
        )

    try:
        resp = requests.post(webhook_url, json={"blocks": blocks}, timeout=10)
        resp.raise_for_status()
        logger.info("Slack report sent: %s", name)
        return True
    except Exception:
        logger.exception("Failed to send Slack report: %s", name)
        return False


def main():
    """Run scheduled reports based on secrets.toml configuration."""
    secrets = _load_secrets()
    reports = secrets.get("reports", [])
    if not reports:
        logger.info("No reports configured in secrets.toml")
        return

    # Load data from SQLite cache
    cache = SamCartCache()
    charges_df = cache.get_charges_df()
    orders_df = cache.get_orders_df()
    subscriptions_df = cache.get_subscriptions_df()

    summary_df = build_daily_summary(orders_df, charges_df, subscriptions_df)

    slack_cfg = secrets.get("slack", {})
    default_webhook = slack_cfg.get("webhook_url", "")

    sent = 0
    for report in reports:
        name = report.get("name", "Unnamed Report")
        frequency = report.get("frequency", "daily")
        channel = report.get("channel", "email")
        destination = report.get("destination", "")
        products = report.get("products", [])

        if not _is_report_due(frequency):
            logger.info(
                "Skipping %s (not due today, frequency=%s)", name, frequency
            )
            continue

        logger.info("Generating report: %s", name)

        if channel == "email":
            html = _format_html_report(name, summary_df, products or None)
            success = _send_email(secrets, destination, name, html)
        elif channel == "slack":
            webhook = destination or default_webhook
            success = _send_slack(
                webhook, name, summary_df, products or None
            )
        else:
            logger.warning(
                "Unknown channel %s for report %s", channel, name
            )
            success = False

        if success:
            sent += 1
        logger.info(
            "Report %s: %s", name, "sent" if success else "FAILED"
        )

    cache.conn.close()
    logger.info(
        "Report run complete: %d/%d reports sent", sent, len(reports)
    )


if __name__ == "__main__":
    main()
