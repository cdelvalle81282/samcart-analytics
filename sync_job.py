"""Headless sync job for cron / manual runs."""

import os
import sys

from samcart_api import SamCartClient
from cache import SamCartCache


def _load_api_key():
    """Load API key from env var, falling back to secrets.toml."""
    api_key = os.environ.get("SAMCART_API_KEY")
    if api_key:
        return api_key

    secrets_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".streamlit", "secrets.toml"
    )
    try:
        import tomllib

        with open(secrets_path, "rb") as f:
            api_key = tomllib.load(f).get("SAMCART_API_KEY")
    except (FileNotFoundError, ImportError):
        pass

    return api_key


def main():
    api_key = _load_api_key()
    if not api_key:
        print("ERROR: SAMCART_API_KEY not set (checked env and secrets.toml)")
        sys.exit(1)

    client = SamCartClient(api_key)
    if not client.verify_credentials():
        print("ERROR: Invalid API key")
        sys.exit(1)

    cache = SamCartCache()
    total = cache.sync_all(client, force_full=False, headless=True)
    print(f"Synced {total:,} records")

    # Checkpoint WAL so all data is in the main .db file for git commit
    cache.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    cache.conn.close()


if __name__ == "__main__":
    main()
