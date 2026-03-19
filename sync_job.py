"""Headless sync job for GitHub Actions cron."""

import os
import sys

from samcart_api import SamCartClient
from cache import SamCartCache


def main():
    api_key = os.environ.get("SAMCART_API_KEY")
    if not api_key:
        print("ERROR: SAMCART_API_KEY not set")
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
