"""Manager notification system — email and Slack report delivery."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from html import escape

import pandas as pd
import requests

from email_sender import send_report_email

logger = logging.getLogger(__name__)


class NotificationChannel(Enum):
    EMAIL = "email"
    SLACK = "slack"


class NotificationFrequency(Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class ManagerConfig:
    name: str
    channel: NotificationChannel
    frequency: NotificationFrequency
    destination: str  # email address or Slack webhook URL
    products: list[str] = field(default_factory=list)  # empty = all products


def format_daily_report(summary_df: pd.DataFrame, manager: ManagerConfig) -> str:
    """Format a daily summary into an HTML report."""
    if summary_df.empty:
        return "<p>No data available for this period.</p>"

    # Filter by products if specified
    df = summary_df.copy()
    if manager.products and "product_name" in df.columns:
        df = df[df["product_name"].isin(manager.products)]

    # Build HTML table
    html = f"<h2>{escape(manager.name)}</h2>\n"
    html += (
        "<table border='1' cellpadding='8' cellspacing='0'"
        " style='border-collapse:collapse;'>\n"
    )
    html += "<tr>"
    for col in df.columns:
        html += f"<th style='background:#f0f0f0;'>{escape(str(col))}</th>"
    html += "</tr>\n"
    for _, row in df.iterrows():
        html += "<tr>"
        for col in df.columns:
            val = row[col]
            if isinstance(val, float):
                html += f"<td>{escape(f'${val:,.2f}')}</td>"
            else:
                html += f"<td>{escape(str(val))}</td>"
        html += "</tr>\n"
    html += "</table>"
    return html


def send_slack_report(
    webhook_url: str,
    report_name: str,
    summary_df: pd.DataFrame,
    products: list[str] | None = None,
) -> bool:
    """Send a formatted report to Slack via incoming webhook."""
    if not webhook_url:
        logger.error("Slack webhook URL not configured")
        return False

    df = summary_df.copy()
    if products and "product_name" in df.columns:
        df = df[df["product_name"].isin(products)]

    # Build Slack blocks
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": report_name}},
        {"type": "divider"},
    ]

    if df.empty:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "No data available for this period.",
                },
            }
        )
    else:
        # Summary text
        lines = []
        for _, row in df.head(20).iterrows():
            parts = []
            for col in df.columns:
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

    payload = {"blocks": blocks}

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Slack report sent: %s", report_name)
        return True
    except Exception:
        logger.exception("Failed to send Slack report: %s", report_name)
        return False


def send_email_notification(
    destination: str, report_name: str, html_body: str
) -> bool:
    """Send report via email using the email_sender module."""
    return send_report_email(destination, report_name, html_body)


def dispatch_notifications(
    summary_df: pd.DataFrame,
    managers: list[ManagerConfig],
    sender=None,  # kept for backward compat, ignored
) -> dict[str, bool]:
    """Send reports to all configured managers. Returns {name: success} dict."""
    results: dict[str, bool] = {}
    for mgr in managers:
        try:
            if mgr.channel == NotificationChannel.EMAIL:
                html = format_daily_report(summary_df, mgr)
                success = send_email_notification(
                    mgr.destination, mgr.name, html
                )
            elif mgr.channel == NotificationChannel.SLACK:
                success = send_slack_report(
                    mgr.destination,
                    mgr.name,
                    summary_df,
                    mgr.products or None,
                )
            else:
                logger.warning("Unknown channel: %s", mgr.channel)
                success = False
            results[mgr.name] = success
        except Exception:
            logger.exception(
                "Failed to dispatch notification for %s", mgr.name
            )
            results[mgr.name] = False
    return results
