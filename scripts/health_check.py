"""Health check: verifies the dashboard is up and the SamCart API is reachable.

Reads from environment:
  APP_URL            — base URL of the dashboard (default: https://opisamcart.duckdns.org)
  SAMCART_API_KEY    — SamCart API key
  SLACK_BOT_TOKEN    — Slack bot token for alerts
  SLACK_ALERT_CHANNEL — Slack channel ID or user ID to receive alerts
"""

import os
import sys

import requests

APP_URL = os.environ.get("APP_URL", "https://opisamcart.duckdns.org")
SAMCART_API_BASE = "https://api.samcart.com/v1"
TIMEOUT = 15


def check_dashboard() -> str | None:
    """Returns an error string, or None if healthy."""
    url = f"{APP_URL}/_stcore/health"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code == 200:
            return None
        return f"HTTP {r.status_code}"
    except requests.ConnectionError:
        return "connection refused (server may be down)"
    except requests.Timeout:
        return f"timed out after {TIMEOUT}s"
    except requests.RequestException as exc:
        return type(exc).__name__


def check_samcart_api(api_key: str) -> str | None:
    """Returns an error string, or None if healthy."""
    if not api_key:
        return "SAMCART_API_KEY not set"
    try:
        r = requests.get(
            f"{SAMCART_API_BASE}/customers",
            headers={"sc-api": api_key},
            params={"limit": 1},
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            return None
        if r.status_code == 401:
            return "HTTP 401 — API key rejected"
        return f"HTTP {r.status_code}"
    except requests.ConnectionError:
        return "connection refused"
    except requests.Timeout:
        return f"timed out after {TIMEOUT}s"
    except requests.RequestException as exc:
        return type(exc).__name__


def send_slack_alert(bot_token: str, channel: str, failures: list[str]) -> None:
    lines = "\n".join(failures)
    payload = {
        "channel": channel,
        "text": lines,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": lines},
            }
        ],
    }
    try:
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {bot_token}"},
            json=payload,
            timeout=10,
        )
        data = resp.json()
        if not data.get("ok"):
            print(f"Slack error: {data.get('error', 'unknown')}", file=sys.stderr)
    except Exception as exc:
        print(f"Failed to send Slack alert: {exc}", file=sys.stderr)


def main() -> int:
    api_key = os.environ.get("SAMCART_API_KEY", "")
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    channel = os.environ.get("SLACK_ALERT_CHANNEL", "")

    failures: list[str] = []

    err = check_dashboard()
    if err:
        failures.append(f":rotating_light: *Dashboard DOWN* — {err}\n<{APP_URL}|{APP_URL}>")
        print(f"FAIL  dashboard: {err}")
    else:
        print(f"OK    dashboard: {APP_URL}")

    err = check_samcart_api(api_key)
    if err:
        failures.append(f":rotating_light: *SamCart API DOWN* — {err}")
        print(f"FAIL  samcart api: {err}")
    else:
        print("OK    samcart api")

    if failures:
        if bot_token and channel:
            send_slack_alert(bot_token, channel, failures)
            print("Alert sent to Slack.")
        else:
            print("WARNING: Slack not configured — set SLACK_BOT_TOKEN and SLACK_ALERT_CHANNEL", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
