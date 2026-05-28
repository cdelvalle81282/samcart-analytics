"""Auto-diagnosis: called by GitHub Actions when health check fails.

Collects context from a file, calls Claude API to diagnose,
posts findings as a GitHub issue comment (or creates an issue if none exists).

Required env vars:
  ANTHROPIC_API_KEY
  GH_TOKEN                — GitHub token (set automatically in Actions)
  GH_REPO                 — owner/repo  (e.g. cdelvalle81282/samcart-analytics)
  FAILURE_CONTEXT_PATH    — path to JSON file: {checks: [{name, error}], logs: str}

Optional:
  ISSUE_NUMBER            — existing issue to comment on (else creates new one)
"""

import json
import os
import re
import sys

import requests

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
GH_API = "https://api.github.com"
MODEL = "claude-opus-4-7"

SYSTEM_PROMPT = """\
You are an on-call SRE assistant for a Streamlit analytics dashboard deployed on a DigitalOcean droplet.
The stack is: Python 3.12, Streamlit, SQLite (WAL), systemd service named samcart-analytics, nginx reverse proxy, Certbot SSL.
The app is at https://opisamcart.duckdns.org and the repo is on GitHub.

When given a health check failure report with server logs, you:
1. Identify the root cause concisely.
2. State whether it is auto-recoverable (e.g. OOM restart, disk full, crashed process) or needs a code fix.
3. Provide the exact shell commands to fix it if recoverable, or a clear description of what code change is needed.
4. Keep the response under 400 words. Use GitHub-flavored markdown.
"""

# Patterns to strip from logs before they leave the runner (public repo)
_REDACT_PATTERNS = [
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"sc-api[^\s\"']*"), "sc-api [REDACTED]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9_\-.]+"), "Bearer [REDACTED]"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-.]+"), "[REDACTED]"),
]


def _redact(text: str) -> str:
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _format_checks(context: dict) -> tuple[str, str]:
    """Return (checks_summary markdown, redacted logs string)."""
    checks_summary = "\n".join(
        f"- **{c['name']}**: {c['error']}" for c in context.get("checks", [])
    )
    logs = _redact(context.get("logs", "(no logs collected)"))
    return checks_summary, logs


def call_claude(api_key: str, context: dict) -> str:
    checks_summary, logs = _format_checks(context)
    user_message = (
        "## Health Check Failure Report\n\n"
        f"### Failed checks\n{checks_summary}\n\n"
        f"### Server logs (last 100 lines)\n```\n{logs[:6000]}\n```\n\n"
        "What is the root cause and how should it be fixed?"
    )
    try:
        resp = requests.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 1024,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_message}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]
    except requests.RequestException as exc:
        raise RuntimeError(type(exc).__name__) from None


def gh_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def create_issue(token: str, repo: str, context: dict) -> int:
    checks_summary, _ = _format_checks(context)
    body = (
        "## Automated Health Check Failure\n\n"
        f"### Failed checks\n{checks_summary}\n\n"
        "_Server logs are included in the Claude diagnosis comment below._\n\n"
        "_Created automatically by the health check workflow._"
    )
    try:
        resp = requests.post(
            f"{GH_API}/repos/{repo}/issues",
            headers=gh_headers(token),
            json={"title": "Health check failure", "body": body, "labels": ["health-alert"]},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(type(exc).__name__) from None
    number = resp.json()["number"]
    print(f"Created issue #{number}")
    return number


def post_comment(token: str, repo: str, issue_number: int, body: str) -> None:
    try:
        resp = requests.post(
            f"{GH_API}/repos/{repo}/issues/{issue_number}/comments",
            headers=gh_headers(token),
            json={"body": body},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(type(exc).__name__) from None
    print(f"Posted comment on issue #{issue_number}")


def main() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    gh_token = os.environ.get("GH_TOKEN", "")
    repo = os.environ.get("GH_REPO", "")
    issue_number_env = os.environ.get("ISSUE_NUMBER", "")

    ctx_path = os.environ.get("FAILURE_CONTEXT_PATH", "")
    if not ctx_path:
        print("FAILURE_CONTEXT_PATH not set", file=sys.stderr)
        return 1
    try:
        with open(ctx_path) as f:
            context = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Failed to read context: {type(exc).__name__}", file=sys.stderr)
        return 1

    # Create or reuse issue
    if issue_number_env:
        issue_number: int | None = int(issue_number_env)
    elif gh_token and repo:
        try:
            issue_number = create_issue(gh_token, repo, context)
        except RuntimeError as exc:
            print(f"Issue creation failed: {exc}", file=sys.stderr)
            issue_number = None
    else:
        print("No GH_TOKEN/GH_REPO — skipping issue creation")
        issue_number = None

    # Auto-diagnose if API key available
    if api_key:
        print("Calling Claude for diagnosis...")
        try:
            diagnosis = call_claude(api_key, context)
            comment = f"## Claude Diagnosis\n\n{diagnosis}\n\n_Auto-generated by diagnose.py_"
            if issue_number and gh_token and repo:
                post_comment(gh_token, repo, issue_number, comment)
            else:
                print(comment)
        except RuntimeError as exc:
            print(f"Diagnosis failed: {exc}", file=sys.stderr)
    else:
        print("ANTHROPIC_API_KEY not set — skipping auto-diagnosis.")
        if issue_number:
            print(f"Issue #{issue_number} created. Open Claude Code and investigate issue #{issue_number}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
