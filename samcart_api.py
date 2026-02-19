"""SamCart API client with auth, pagination, rate limiting, and credential verification."""

import time
from datetime import datetime, timezone

import requests


def normalize_ts(ts_str: str) -> str | None:
    """Convert any ISO 8601 timestamp to UTC for consistent storage."""
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return None


def safe_float(val, default=0.0) -> float:
    """Coerce API value to float, handling None/empty/string."""
    if val is None or val == "" or val == "null":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val, default=0) -> int:
    """Coerce API value to int, handling None/empty/string."""
    if val is None or val == "" or val == "null":
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


class SamCartAPIError(Exception):
    """Sanitized API error — never includes auth headers."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"SamCart API error {status_code}: {message}")


class SamCartClient:
    """Client for the SamCart v1 REST API."""

    BASE_URL = "https://api.samcart.com/v1"
    MAX_RETRIES = 5
    INITIAL_BACKOFF = 1.0  # seconds

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key}"
        # SECURITY: Never set verify=False
        self.session.verify = True

    def verify_credentials(self) -> bool:
        """Hit /customers?limit=1 to validate the API key. Returns True/False."""
        try:
            resp = self.session.get(
                f"{self.BASE_URL}/customers",
                params={"limit": 1},
                timeout=30,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def _request(self, endpoint: str, params: dict | None = None) -> dict:
        """
        Make a GET request with retry/backoff for 429s.

        SECURITY: Never logs Authorization header. Catches RequestException
        and surfaces sanitized error messages (no Bearer token in tracebacks).
        """
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        backoff = self.INITIAL_BACKOFF

        for attempt in range(self.MAX_RETRIES):
            try:
                resp = self.session.get(url, params=params, timeout=30)
            except requests.RequestException as exc:
                # Sanitize — strip any header content from the message
                raise SamCartAPIError(0, f"Network error: {type(exc).__name__}") from None

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code == 401:
                raise SamCartAPIError(401, "Invalid API key")

            if resp.status_code == 429:
                # Rate limited — exponential backoff
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else backoff
                time.sleep(wait)
                backoff *= 2
                continue

            raise SamCartAPIError(resp.status_code, f"Unexpected status {resp.status_code}")

        raise SamCartAPIError(429, "Rate limit exceeded after max retries")

    def _paginate(self, endpoint: str, params: dict | None = None) -> list[dict]:
        """Fetch all pages from a paginated endpoint."""
        params = dict(params or {})
        all_items = []
        page = 1

        while True:
            params["page"] = page
            data = self._request(endpoint, params)

            # SamCart wraps results in a "data" key
            items = data.get("data", [])
            if not items:
                break

            all_items.extend(items)

            # Check pagination metadata
            pagination = data.get("pagination", {})
            total_pages = pagination.get("last_page", 1)
            if page >= total_pages:
                break

            page += 1

        return all_items

    def get_orders(self, since: str | None = None) -> list[dict]:
        """Fetch orders, optionally filtering by created_at >= since."""
        params = {}
        if since:
            params["created_at_min"] = since
        return self._paginate("orders", params)

    def get_customers(self, since: str | None = None) -> list[dict]:
        """Fetch customers, optionally filtering by created_at >= since."""
        params = {}
        if since:
            params["created_at_min"] = since
        return self._paginate("customers", params)

    def get_subscriptions(self, since: str | None = None) -> list[dict]:
        """Fetch subscriptions, optionally filtering by created_at >= since."""
        params = {}
        if since:
            params["created_at_min"] = since
        return self._paginate("subscriptions", params)

    def get_products(self) -> list[dict]:
        """Fetch all products (typically small table)."""
        return self._paginate("products")

    def get_charges(self, since: str | None = None) -> list[dict]:
        """Fetch charges, optionally filtering by created_at >= since."""
        params = {}
        if since:
            params["created_at_min"] = since
        return self._paginate("charges", params)
