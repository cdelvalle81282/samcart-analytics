"""Health check: verifies the dashboard is up and the SamCart API is reachable.

Reads from environment:
  APP_URL             — base URL of the dashboard (default: https://opisamcart.duckdns.org)
  SAMCART_API_KEY     — SamCart API key
  SLACK_BOT_TOKEN     — Slack bot token for alerts
  SLACK_ALERT_CHANNEL — Slack channel ID or user ID to receive alerts

Flags:
  --json-output PATH  — write check results as JSON to PATH and exit 0 regardless
                        of outcome (used by the diagnose job to capture error details)
"""

import json
import os
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

_ALLOWED_APP_HOSTS = {"opisamcart.duckdns.org"}
SAMCART_API_BASE = "https://api.samcart.com/v1"
TIMEOUT = 15


def _validated_app_url() -> str:
    url = os.environ.get("APP_URL", "https://opisamcart.duckdns.org")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_APP_HOSTS:
        raise SystemExit(f"APP_URL not in allowlist: {url}")
    return url


APP_URL = _validated_app_url()


def check_dashboard() -> tuple[str, str | None]:
    """Return (name, error_or_None)."""
    url = f"{APP_URL}/_stcore/health"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code == 200:
            return "dashboard", None
        return "dashboard", f"HTTP {r.status_code}"
    except requests.ConnectionError:
        return "dashboard", "connection refused (server may be down)"
    except requests.Timeout:
        return "dashboard", f"timed out after {TIMEOUT}s"
    except requests.RequestException as exc:
        return "dashboard", type(exc).__name__


def check_samcart_api(api_key: str) -> tuple[str, str | None]:
    """Return (name, error_or_None)."""
    if not api_key:
        return "samcart_api", "SAMCART_API_KEY not set"
    try:
        r = requests.get(
            f"{SAMCART_API_BASE}/customers",
            headers={"sc-api": api_key},
            params={"limit": 1},
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            return "samcart_api", None
        if r.status_code == 401:
            return "samcart_api", "HTTP 401 — API key rejected"
        return "samcart_api", f"HTTP {r.status_code}"
    except requests.ConnectionError:
        return "samcart_api", "connection refused"
    except requests.Timeout:
        return "samcart_api", f"timed out after {TIMEOUT}s"
    except requests.RequestException as exc:
        return "samcart_api", type(exc).__name__


def _with_retry(fn, *, attempts: int = 2, delay: float = 5) -> tuple[str, str | None]:
    """Call fn() up to `attempts` times, returning on first success."""
    result: tuple[str, str | None] = ("unknown", "never ran")
    for i in range(attempts):
        if i:
            time.sleep(delay)
        result = fn()
        if result[1] is None:
            return result
    return result


def send_slack_alert(bot_token: str, channel: str, failures: list[str]) -> None:
    lines = "\n".join(failures)
    payload = {
        "channel": channel,
        "text": lines,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": lines}}],
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
    except requests.RequestException as exc:
        print(f"Failed to send Slack alert: {type(exc).__name__}", file=sys.stderr)


def run_checks(api_key: str) -> list[tuple[str, str | None]]:
    """Run both checks concurrently with retry. Returns list of (name, error_or_None)."""
    fns = [
        check_dashboard,
        lambda: check_samcart_api(api_key),
    ]
    _names = ("dashboard", "samcart_api")
    results = [None, None]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(_with_retry, fn): i for i, fn in enumerate(fns)}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                results[idx] = (_names[idx], type(exc).__name__)
    return results


def main() -> int:
    json_output = None
    if "--json-output" in sys.argv:
        idx = sys.argv.index("--json-output")
        json_output = sys.argv[idx + 1]

    api_key = os.environ.get("SAMCART_API_KEY", "")
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    channel = os.environ.get("SLACK_ALERT_CHANNEL", "")

    results = run_checks(api_key)

    failures: list[str] = []
    checks_out: list[dict] = []
    for name, error in results:
        if error:
            failures.append(f":rotating_light: *{name} DOWN* — {error}")
            checks_out.append({"name": name, "error": error})
            print(f"FAIL  {name}: {error}")
        else:
            print(f"OK    {name}")

    if json_output is not None:
        with open(json_output, "w") as f:
            json.dump({"checks": checks_out, "healthy": len(failures) == 0}, f)
        return 0

    if failures:
        if bot_token and channel:
            send_slack_alert(bot_token, channel, failures)
            print("Alert sent to Slack.")
        else:
            print(
                "WARNING: Slack not configured — set SLACK_BOT_TOKEN and SLACK_ALERT_CHANNEL",
                file=sys.stderr,
            )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
