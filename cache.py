"""SQLite cache for SamCart data with hybrid sync strategy."""

import os
import sqlite3
import stat
import time as _time
from datetime import date, datetime, time as _dt_time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from samcart_api import SamCartClient, normalize_ts, safe_float, safe_int


_ALLOWED_TABLES = frozenset({"orders", "customers", "subscriptions", "charges", "products", "sync_meta", "audit_log", "pii_access_requests"})


def _validate_table(table_name: str) -> str:
    """Validate table name against whitelist to prevent SQL injection."""
    if table_name not in _ALLOWED_TABLES:
        raise ValueError(f"Invalid table name: {table_name}")
    return table_name


class SamCartCache:
    """Local SQLite cache with extracted columns only (no raw_json)."""

    def __init__(self, db_path: str = "samcart_cache.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self._init_schema()
        self._migrate_schema()
        # Restrict DB file to owner-only (effective on Linux deployment target)
        if os.path.exists(self.db_path):
            os.chmod(self.db_path, stat.S_IRUSR | stat.S_IWUSR)

    def _migrate_schema(self):
        """Add new columns to existing tables if missing (idempotent)."""
        migrations = [
            ("subscriptions", "trial_days", "INTEGER"),
            ("subscriptions", "next_bill_date", "TEXT"),
            ("subscriptions", "billing_cycle_count", "INTEGER"),
            ("charges", "refund_amount", "REAL"),
            ("charges", "refund_date", "TEXT"),
        ]
        for table, column, col_type in migrations:
            safe_table = _validate_table(table)
            existing = {
                row[1]
                for row in self.conn.execute(f"PRAGMA table_info({safe_table})").fetchall()
            }
            if column not in existing:
                self.conn.execute(
                    f"ALTER TABLE {safe_table} ADD COLUMN {column} {col_type}"
                )
        self.conn.commit()

    def _init_schema(self):
        """Create tables and indexes if they don't exist."""
        cur = self.conn.cursor()

        cur.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                customer_email TEXT,
                customer_id TEXT,
                product_id TEXT,
                product_name TEXT,
                total REAL,
                created_at TEXT,
                subscription_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
            CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_email);
            CREATE INDEX IF NOT EXISTS idx_orders_product ON orders(product_id);

            CREATE TABLE IF NOT EXISTS customers (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                first_name TEXT,
                last_name TEXT,
                phone TEXT,
                billing_city TEXT,
                billing_state TEXT,
                billing_country TEXT,
                created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_customers_email ON customers(email);

            CREATE TABLE IF NOT EXISTS subscriptions (
                id TEXT PRIMARY KEY,
                customer_email TEXT,
                product_id TEXT,
                product_name TEXT,
                status TEXT,
                interval TEXT,
                price REAL,
                created_at TEXT,
                canceled_at TEXT,
                trial_days INTEGER,
                next_bill_date TEXT,
                billing_cycle_count INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_subs_status ON subscriptions(status);
            CREATE INDEX IF NOT EXISTS idx_subs_created ON subscriptions(created_at);
            CREATE INDEX IF NOT EXISTS idx_subs_customer ON subscriptions(customer_email);

            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                name TEXT,
                price REAL,
                sku TEXT
            );

            CREATE TABLE IF NOT EXISTS charges (
                id TEXT PRIMARY KEY,
                order_id TEXT,
                subscription_id TEXT,
                customer_email TEXT,
                amount REAL,
                status TEXT,
                created_at TEXT,
                refund_amount REAL,
                refund_date TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_charges_created ON charges(created_at);
            CREATE INDEX IF NOT EXISTS idx_charges_customer ON charges(customer_email);
            CREATE INDEX IF NOT EXISTS idx_charges_subscription ON charges(subscription_id);

            CREATE TABLE IF NOT EXISTS sync_meta (
                table_name TEXT PRIMARY KEY,
                last_synced_at TEXT,
                record_count INTEGER
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                username TEXT NOT NULL,
                ip_address TEXT,
                action TEXT NOT NULL,
                resource TEXT,
                detail TEXT,
                outcome TEXT NOT NULL CHECK(outcome IN ('approved','denied','auto','error','pending'))
            );
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
        """)
        self.conn.commit()

    # ------------------------------------------------------------------
    # Sync metadata
    # ------------------------------------------------------------------

    def get_last_sync(self, table_name: str) -> str | None:
        """Returns last_synced_at ISO timestamp for incremental fetching."""
        row = self.conn.execute(
            "SELECT last_synced_at FROM sync_meta WHERE table_name = ?",
            (table_name,),
        ).fetchone()
        return row[0] if row else None

    def _incremental_since(self, table_name: str) -> str | None:
        """Calculate the since timestamp with 1-hour overlap for incremental sync."""
        last_sync = self.get_last_sync(table_name)
        if last_sync:
            dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
            return (dt - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return None

    def _update_sync_meta(self, table_name: str, commit: bool = True):
        """Update sync_meta with current time and record count."""
        _validate_table(table_name)
        count = self.conn.execute(
            f"SELECT COUNT(*) FROM [{table_name}]"
        ).fetchone()[0]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.conn.execute(
            "INSERT OR REPLACE INTO sync_meta (table_name, last_synced_at, record_count) VALUES (?, ?, ?)",
            (table_name, now, count),
        )
        if commit:
            self.conn.commit()

    def get_sync_summary(self) -> dict:
        """Returns {table_name: {last_synced_at, record_count}} for sidebar display."""
        rows = self.conn.execute(
            "SELECT table_name, last_synced_at, record_count FROM sync_meta"
        ).fetchall()
        return {
            row[0]: {"last_synced_at": row[1], "record_count": row[2]}
            for row in rows
        }

    # ------------------------------------------------------------------
    # Upsert helpers — extract only whitelisted fields
    # ------------------------------------------------------------------

    def _upsert_orders(self, orders: list[dict], customer_map: dict | None = None):
        """INSERT OR REPLACE orders, extracting only needed fields."""
        customer_map = customer_map or {}
        for order in orders:
            customer_id = str(order.get("customer_id", ""))
            customer_email = customer_map.get(customer_id, "")

            # Product info is nested in cart_items; take first item
            cart_items = order.get("cart_items") or []
            first_item = cart_items[0] if cart_items else {}
            product_id = str(first_item.get("product_id", ""))
            product_name = first_item.get("product_name", "")
            subscription_id = str(first_item.get("subscription_id", "") or "")

            self.conn.execute(
                """INSERT OR REPLACE INTO orders
                   (id, customer_email, customer_id, product_id, product_name, total, created_at, subscription_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(order.get("id", "")),
                    customer_email,
                    customer_id,
                    product_id,
                    product_name,
                    safe_float(order.get("total")) / 100,
                    normalize_ts(order.get("order_date") or order.get("created_at")),
                    subscription_id,
                ),
            )

    def _upsert_customers(self, customers: list[dict]):
        """INSERT OR REPLACE customers with PII minimization."""
        for c in customers:
            # Billing address is in addresses array with type="billing"
            addresses = c.get("addresses") or []
            billing = {}
            for addr in addresses:
                if addr.get("type") == "billing":
                    billing = addr
                    break

            self.conn.execute(
                """INSERT OR REPLACE INTO customers
                   (id, email, first_name, last_name, phone, billing_city, billing_state, billing_country, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(c.get("id", "")),
                    c.get("email", ""),
                    c.get("first_name", ""),
                    c.get("last_name", ""),
                    c.get("phone", ""),
                    billing.get("city", ""),
                    billing.get("state", ""),
                    billing.get("country", ""),
                    normalize_ts(c.get("created_at")),
                ),
            )

    def _upsert_subscriptions(self, subs: list[dict], customer_map: dict | None = None):
        """INSERT OR REPLACE subscriptions."""
        customer_map = customer_map or {}
        for s in subs:
            customer_id = str(s.get("customer_id", ""))
            customer_email = customer_map.get(customer_id, "")

            # Price is nested in recurring_price
            recurring_price = s.get("recurring_price") or {}
            price = safe_float(recurring_price.get("total", s.get("price"))) / 100

            # canceled_at maps to end_date when status is canceled
            canceled_at = s.get("end_date") if s.get("status") == "canceled" else None

            self.conn.execute(
                """INSERT OR REPLACE INTO subscriptions
                   (id, customer_email, product_id, product_name, status, interval, price, created_at, canceled_at,
                    trial_days, next_bill_date, billing_cycle_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(s.get("id", "")),
                    customer_email,
                    str(s.get("product_id", "")),
                    s.get("product_name", ""),
                    s.get("status", ""),
                    s.get("subscription_interval", ""),
                    price,
                    normalize_ts(s.get("created_at")),
                    normalize_ts(canceled_at),
                    safe_int(s.get("trial_days")),
                    normalize_ts(s.get("next_rebilling_date") or s.get("next_bill_date")),
                    safe_int(s.get("billing_cycle_count")),
                ),
            )

    def _upsert_products(self, products: list[dict]):
        """INSERT OR REPLACE products."""
        for p in products:
            self.conn.execute(
                """INSERT OR REPLACE INTO products (id, name, price, sku) VALUES (?, ?, ?, ?)""",
                (
                    str(p.get("id", "")),
                    p.get("product_name", p.get("name", "")),
                    safe_float(p.get("price")) / 100,
                    p.get("sku", ""),
                ),
            )

    def _upsert_charges(self, charges: list[dict], customer_map: dict | None = None):
        """Upsert charges, preserving refund fields managed by _sync_refunds."""
        customer_map = customer_map or {}
        for ch in charges:
            customer_id = str(ch.get("customer_id", ""))
            customer_email = customer_map.get(customer_id, "")

            self.conn.execute(
                """INSERT INTO charges
                   (id, order_id, subscription_id, customer_email, amount, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       order_id=excluded.order_id,
                       subscription_id=excluded.subscription_id,
                       customer_email=excluded.customer_email,
                       amount=excluded.amount,
                       status=excluded.status,
                       created_at=excluded.created_at""",
                (
                    str(ch.get("id", "")),
                    str(ch.get("order_id", "") or ""),
                    str(ch.get("subscription_rebill_id", "") or ""),
                    customer_email,
                    safe_float(ch.get("total", ch.get("amount"))) / 100,
                    ch.get("charge_refund_status", ch.get("status", "")),
                    normalize_ts(ch.get("created_at")),
                ),
            )

    # ------------------------------------------------------------------
    # Refund sync — updates charges with refund data from /refunds
    # ------------------------------------------------------------------

    def _sync_refunds(self, client: SamCartClient, headless: bool = False):
        """Fetch refunds and update charges with aggregated refund amounts/dates."""
        if headless:
            print("Fetching refunds...")
        refunds = client.get_refunds()
        if not refunds:
            return []

        # Group refunds by charge_id: sum amounts, take latest date
        charge_refunds: dict[str, dict] = {}
        for r in refunds:
            charge_id = str(r.get("charge_id", ""))
            if not charge_id:
                continue
            amount = safe_float(r.get("refund_amount", r.get("amount"))) / 100
            refund_date = normalize_ts(r.get("created_at"))

            if charge_id in charge_refunds:
                charge_refunds[charge_id]["amount"] += amount
                if refund_date and (
                    not charge_refunds[charge_id]["date"]
                    or refund_date > charge_refunds[charge_id]["date"]
                ):
                    charge_refunds[charge_id]["date"] = refund_date
            else:
                charge_refunds[charge_id] = {"amount": amount, "date": refund_date}

        # Update charges table
        for charge_id, data in charge_refunds.items():
            self.conn.execute(
                "UPDATE charges SET refund_amount = ?, refund_date = ? WHERE id = ?",
                (data["amount"], data["date"], charge_id),
            )
        self.conn.commit()

        if headless:
            print(f"  Updated {len(charge_refunds)} charges with refund data")
        return refunds

    # ------------------------------------------------------------------
    # Sync engine — hybrid strategy
    # ------------------------------------------------------------------

    def _sync_table(
        self,
        table_name: str,
        fetcher,
        upserter,
        since: str | None = None,
        force_full: bool = False,
        progress_text: str = "",
        customer_map: dict | None = None,
        headless: bool = False,
    ):
        """Sync a single table: fetch from API, upsert into SQLite, update meta."""
        _validate_table(table_name)
        if force_full:
            since = None

        if progress_text:
            if headless:
                print(progress_text)
            else:
                st.text(progress_text)

        if since is not None:
            records = fetcher(since=since)
        else:
            # fetcher might not accept since kwarg (e.g. get_products)
            try:
                records = fetcher(since=since)
            except TypeError:
                records = fetcher()

        batch_size = 100
        if force_full:
            # Replace full-sync tables atomically so failures preserve prior data.
            try:
                self.conn.execute("BEGIN")
                self.conn.execute(f"DELETE FROM [{table_name}]")
                for i in range(0, len(records), batch_size):
                    batch = records[i : i + batch_size]
                    if customer_map is not None:
                        upserter(batch, customer_map=customer_map)
                    else:
                        upserter(batch)
                self._update_sync_meta(table_name, commit=False)
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        else:
            if records:
                # Commit per batch for crash safety on incremental syncs.
                for i in range(0, len(records), batch_size):
                    batch = records[i : i + batch_size]
                    if customer_map is not None:
                        upserter(batch, customer_map=customer_map)
                    else:
                        upserter(batch)
                    self.conn.commit()
            self._update_sync_meta(table_name)
        return records or []

    def _build_customer_map(self) -> dict:
        """Build customer_id -> email lookup from the customers table."""
        rows = self.conn.execute("SELECT id, email FROM customers").fetchall()
        return {str(row[0]): row[1] for row in rows}

    def sync_all(self, client: SamCartClient, force_full: bool = False, headless: bool = False):
        """
        Hybrid sync strategy:
        - products: always full (small table)
        - customers: sync first to build id->email map
        - subscriptions: always full (status is mutable)
        - charges: always full (refund status is mutable)
        - orders: incremental unless force_full

        Incremental uses a 1-hour overlap window + UPSERT to catch boundary records.
        Set headless=True to run without Streamlit UI (e.g. from a CI cron job).
        """
        if headless:
            print("Starting sync...")
        else:
            progress = st.progress(0, text="Starting sync...")
        total_records = 0

        def _timed_sync(label, pct, sync_fn, prefix="Syncing"):
            nonlocal total_records
            if headless:
                print(f"{prefix} {label}...")
            else:
                progress.progress(pct, text=f"{prefix} {label}...")
            t0 = _time.time()
            recs = sync_fn()
            elapsed = _time.time() - t0
            if headless:
                print(f"  {label}: {len(recs)} records in {elapsed:.1f}s")
            total_records += len(recs)

        # Products: always full (small table)
        _timed_sync("products", 0.05, lambda: self._sync_table(
            "products", client.get_products, self._upsert_products,
            force_full=True, headless=headless,
        ))

        # Customers FIRST — needed to map customer_id -> email for other tables
        since = None if force_full else self._incremental_since("customers")
        _timed_sync("customers", 0.15, lambda: self._sync_table(
            "customers", client.get_customers, self._upsert_customers,
            since=since, force_full=force_full, headless=headless,
        ))

        # Build customer_id -> email map from the cache
        customer_map = self._build_customer_map()

        # Subscriptions: ALWAYS full sync — status is mutable
        _timed_sync("subscriptions", 0.35, lambda: self._sync_table(
            "subscriptions", client.get_subscriptions, self._upsert_subscriptions,
            force_full=True, customer_map=customer_map, headless=headless,
        ))

        # Charges: ALWAYS full sync — refund status is mutable
        _timed_sync("charges", 0.55, lambda: self._sync_table(
            "charges", client.get_charges, self._upsert_charges,
            force_full=True, customer_map=customer_map, headless=headless,
        ))

        # Refunds: update charges with refund amounts/dates from /refunds endpoint
        if headless:
            print("Syncing refunds...")
        else:
            progress.progress(0.65, text="Syncing refunds...")
        t0 = _time.time()
        refund_list = self._sync_refunds(client, headless=headless)
        elapsed = _time.time() - t0
        if headless:
            print(f"  refunds: {len(refund_list)} records in {elapsed:.1f}s")

        # Orders: incremental with 1-hour overlap
        since = None if force_full else self._incremental_since("orders")
        _timed_sync("orders", 0.8, lambda: self._sync_table(
            "orders", client.get_orders, self._upsert_orders,
            since=since, force_full=force_full, customer_map=customer_map,
            headless=headless,
        ))

        if headless:
            print("Sync complete!")
        else:
            progress.progress(1.0, text="Sync complete!")
        return total_records

    def sync_today(self, client: SamCartClient, headless: bool = False) -> int:
        """
        Quick sync of today's activity only — new orders and charges since
        midnight Eastern. Intended for intraday use so you can see sales as
        they happen without waiting for the overnight full sync.

        Does NOT update subscription statuses, historical refunds, or products.
        Use sync_all for a complete refresh.
        """
        _ET = ZoneInfo("America/New_York")
        midnight_et = datetime.combine(date.today(), _dt_time.min, tzinfo=_ET)
        # Convert to UTC before formatting — strftime on an ET-aware datetime
        # produces the correct wall-clock digits but the Z suffix would lie to the API.
        since = midnight_et.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        total_records = 0
        if headless:
            print(f"Today's sync (since {midnight_et.strftime('%Y-%m-%d %H:%M %Z')})...")
        else:
            progress = st.progress(0, text="Syncing today's customers...")

        def _timed_today(label, pct, sync_fn):
            nonlocal total_records
            if headless:
                print(f"Syncing today's {label}...")
            else:
                progress.progress(pct, text=f"Syncing today's {label}...")
            t0 = _time.time()
            recs = sync_fn()
            elapsed = _time.time() - t0
            if headless:
                print(f"  {label}: {len(recs)} records in {elapsed:.1f}s")
            total_records += len(recs)

        _timed_today("customers", 0.1, lambda: self._sync_table(
            "customers", client.get_customers, self._upsert_customers,
            since=since, headless=headless,
        ))
        customer_map = self._build_customer_map()

        _timed_today("orders", 0.5, lambda: self._sync_table(
            "orders", client.get_orders, self._upsert_orders,
            since=since, customer_map=customer_map, headless=headless,
        ))

        _timed_today("charges", 0.85, lambda: self._sync_table(
            "charges", client.get_charges, self._upsert_charges,
            since=since, customer_map=customer_map, headless=headless,
        ))

        if headless:
            print(f"Today's sync complete: {total_records} records")
        else:
            progress.progress(1.0, text="Today's sync complete!")
        return total_records

    # ------------------------------------------------------------------
    # Query helpers — return DataFrames
    # ------------------------------------------------------------------

    def get_orders_df(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM orders ORDER BY created_at DESC", self.conn)

    def get_subscriptions_df(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM subscriptions ORDER BY created_at DESC", self.conn)

    def get_customers_df(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM customers ORDER BY created_at DESC", self.conn)

    def get_charges_df(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM charges ORDER BY created_at DESC", self.conn)

    def get_products_df(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM products ORDER BY name", self.conn)

    def search_customers(self, query: str) -> pd.DataFrame:
        """Search customers by email or name. Uses parameterized LIKE with escaped wildcards."""
        if len(query) > 100:
            return pd.DataFrame()
        # Escape LIKE wildcards so they are treated as literals
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        return pd.read_sql_query(
            """SELECT * FROM customers
               WHERE email LIKE ? ESCAPE '\\' OR first_name LIKE ? ESCAPE '\\' OR last_name LIKE ? ESCAPE '\\'
               ORDER BY created_at DESC LIMIT 100""",
            self.conn,
            params=(pattern, pattern, pattern),
        )

    def get_customer_orders(self, email: str) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM orders WHERE customer_email = ? ORDER BY created_at DESC",
            self.conn,
            params=(email,),
        )

    def get_customer_subscriptions(self, email: str) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM subscriptions WHERE customer_email = ? ORDER BY created_at DESC",
            self.conn,
            params=(email,),
        )

    def get_customer_charges(self, email: str) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM charges WHERE customer_email = ? ORDER BY created_at DESC",
            self.conn,
            params=(email,),
        )

    # ------------------------------------------------------------------
    # Audit log helpers
    # ------------------------------------------------------------------

    def log_audit_event(self, username, ip_address, action, resource=None, detail=None, outcome="auto"):
        """Insert an audit log event."""
        self.conn.execute(
            "INSERT INTO audit_log (username, ip_address, action, resource, detail, outcome) VALUES (?, ?, ?, ?, ?, ?)",
            (username, ip_address, action, resource, detail, outcome),
        )
        self.conn.commit()

    def get_audit_log_df(self, days=30, username=None):
        """Return audit log as DataFrame, optionally filtered."""
        query = "SELECT * FROM audit_log WHERE timestamp >= datetime('now', ?)"
        params = [f"-{days} days"]
        if username:
            query += " AND username = ?"
            params.append(username)
        query += " ORDER BY timestamp DESC"
        return pd.read_sql_query(query, self.conn, params=params)

    # ------------------------------------------------------------------
    # GDPR / CCPA deletion
    # ------------------------------------------------------------------

    def delete_customer_data(self, email: str) -> dict[str, int]:
        """Delete all data for a customer by email across all tables. Returns counts."""
        if not email:
            raise ValueError("email is required for GDPR deletion")
        counts = {}
        deletion_pairs = [
            ("orders", "customer_email"),
            ("customers", "email"),
            ("subscriptions", "customer_email"),
            ("charges", "customer_email"),
        ]
        for table, col in deletion_pairs:
            if table not in _ALLOWED_TABLES:
                raise ValueError(f"Invalid table in deletion pair: {table}")
            cur = self.conn.execute(
                f"DELETE FROM [{table}] WHERE [{col}] = ?", (email,)
            )
            counts[table] = cur.rowcount
        self.conn.commit()
        return counts
