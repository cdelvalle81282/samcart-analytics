"""
Diagnostic: New customer count accuracy for a given date range.

Run on the droplet:
    cd /home/samcart/samcart-analytics
    python3 diagnose_new_customers.py

Or locally against a DB file:
    python3 diagnose_new_customers.py --db samcart_cache.db
"""
import sqlite3
import sys

START = "2026-04-24"
END   = "2026-04-26"

def main():
    db_path = "samcart_cache.db"
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--db" and i + 2 <= len(sys.argv) - 1:
            db_path = sys.argv[i + 2]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # ------------------------------------------------------------------
    # 1. DB date range
    # ------------------------------------------------------------------
    row = conn.execute("SELECT MIN(created_at), MAX(created_at), COUNT(*) FROM orders").fetchone()
    print("\n=== Orders in DB ===")
    print(f"  Earliest : {row[0]}")
    print(f"  Latest   : {row[1]}")
    print(f"  Total    : {row[2]:,}")

    # ------------------------------------------------------------------
    # 2. Orders in the target window
    # ------------------------------------------------------------------
    window_orders = conn.execute("""
        SELECT id, customer_email, customer_id, product_name, created_at
        FROM orders
        WHERE date(created_at) BETWEEN ? AND ?
        ORDER BY created_at
    """, (START, END)).fetchall()

    print(f"\n=== Orders in {START} – {END}: {len(window_orders)} ===")

    # ------------------------------------------------------------------
    # 3. For each customer in the window, find their earliest order ever
    # ------------------------------------------------------------------
    print("\n=== Customer classification ===")
    truly_new = []
    existing  = []
    no_email  = []

    emails_in_window = set(r["customer_email"] for r in window_orders)

    for email in sorted(emails_in_window):
        if not email:
            no_email.append(email)
            continue

        earliest = conn.execute("""
            SELECT created_at, product_name FROM orders
            WHERE customer_email = ?
            ORDER BY created_at ASC
            LIMIT 1
        """, (email,)).fetchone()

        order_count = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE customer_email = ?", (email,)
        ).fetchone()[0]

        first_date = earliest["created_at"][:10] if earliest else "?"
        is_in_window = START <= first_date <= END

        # Also check customer record created_at
        cust = conn.execute(
            "SELECT created_at FROM customers WHERE email = ?", (email,)
        ).fetchone()
        cust_created = cust["created_at"][:10] if cust else "not in customers table"

        row_data = {
            "email": email,
            "first_order_date": first_date,
            "first_product": earliest["product_name"] if earliest else "?",
            "order_count": order_count,
            "customer_record_created": cust_created,
        }

        if is_in_window:
            truly_new.append(row_data)
        else:
            existing.append(row_data)

    print(f"\n  Truly new customers (first order ever in window) : {len(truly_new)}")
    for r in truly_new:
        print(f"    {r['email']}  first={r['first_order_date']}  product={r['first_product']}")

    print(f"\n  Existing customers who bought again : {len(existing)}")
    for r in existing:
        print(f"    {r['email']}")
        print(f"      first order : {r['first_order_date']}  ({r['first_product']})")
        print(f"      total orders: {r['order_count']}")
        print(f"      cust record : {r['customer_record_created']}")

    if no_email:
        print(f"\n  Orders with MISSING customer_email : {len(no_email)}")
        blank_orders = conn.execute("""
            SELECT id, customer_id, product_name, created_at
            FROM orders
            WHERE (customer_email IS NULL OR customer_email = '')
              AND date(created_at) BETWEEN ? AND ?
        """, (START, END)).fetchall()
        for r in blank_orders:
            print(f"    order={r['id']} customer_id={r['customer_id']} product={r['product_name']} {r['created_at']}")

    # ------------------------------------------------------------------
    # 4. Check analytics.daily_new_to_file output for window
    # ------------------------------------------------------------------
    print("\n=== What daily_new_to_file() would compute ===")
    # Replicate the logic: find idxmin(created_at) per customer_email across ALL orders
    all_first = conn.execute("""
        SELECT customer_email, MIN(created_at) as first_order_ts, product_name
        FROM orders
        GROUP BY customer_email
    """).fetchall()

    ntf_in_window = [
        r for r in all_first
        if r["first_order_ts"] and START <= r["first_order_ts"][:10] <= END
        and r["customer_email"]
    ]
    print(f"  Customers whose FIRST-EVER order is in {START}–{END}: {len(ntf_in_window)}")
    for r in ntf_in_window:
        print(f"    {r['customer_email']}  first={r['first_order_ts'][:10]}  product={r['product_name']}")

    # Are any of the window-period buyers missing from the NTF list?
    ntf_emails = {r["customer_email"] for r in ntf_in_window}
    missed_existing = [r for r in existing if r["email"] not in ntf_emails]
    if missed_existing:
        print(f"\n  Existing customers correctly NOT counted as new: {len(missed_existing)}")
        for r in missed_existing:
            print(f"    {r['email']} (first order {r['first_order_date']})")
    else:
        print("\n  All existing customers are correctly excluded from NTF count.")

    # ------------------------------------------------------------------
    # 5. Customers appearing as new but whose CUSTOMER RECORD predates window
    # ------------------------------------------------------------------
    suspect = []
    for r in ntf_in_window:
        cust = conn.execute(
            "SELECT created_at FROM customers WHERE email = ?", (r["customer_email"],)
        ).fetchone()
        if cust and cust["created_at"][:10] < START:
            suspect.append({
                "email": r["customer_email"],
                "customer_created": cust["created_at"][:10],
                "first_order_in_db": r["first_order_ts"][:10],
            })

    if suspect:
        print(f"\n  *** SUSPECT: counted as NEW but customer record predates window ({len(suspect)}) ***")
        print("  These customers had accounts before the window — their earliest ORDER in the DB")
        print("  falls in the window, meaning prior orders are MISSING from the DB.")
        for r in suspect:
            print(f"    {r['email']}  customer_created={r['customer_created']}  first_db_order={r['first_order_in_db']}")
    else:
        print("\n  No suspects found — NTF logic appears correct for this window.")

    conn.close()
    print()


if __name__ == "__main__":
    main()
