"""Diagnose new-customer accuracy for 04/24-04/26 by querying the SamCart API."""
import time
import requests
from urllib.parse import urlparse, parse_qs

API_KEY = "MjE4NDIwLjQzMTkwOC5ZMkl3SU9BcGJkYVYxczIwUFpZNEJ4bDkuJ5rKb0C7oR4MNl6gfbz9hw.HR9vmTRQJ6BruZfkINTROSIhhIpjx33ptSztQfESJcI"
BASE    = "https://api.samcart.com/v1"

sess = requests.Session()
sess.headers["sc-api"] = API_KEY
sess.verify = True

START = "2026-04-24"
END   = "2026-04-26"


def get(endpoint, params=None):
    """Single GET with 429 backoff."""
    url = f"{BASE}/{endpoint.lstrip('/')}"
    backoff = 2.0
    for _ in range(6):
        r = sess.get(url, params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            wait = float(r.headers.get("Retry-After", backoff))
            print(f"  [rate limited] waiting {wait:.0f}s...")
            time.sleep(wait)
            backoff *= 2
            continue
        r.raise_for_status()
    raise Exception("Max retries exceeded")


def paginate(endpoint, params=None):
    """Cursor-based pagination following 'next' URLs."""
    params = dict(params or {})
    results = []
    data = get(endpoint, params)
    results.extend(data.get("data", []))
    while True:
        next_url = (data.get("pagination") or {}).get("next")
        if not next_url:
            break
        parsed = urlparse(next_url)
        ep = parsed.path.replace("/v1/", "", 1)
        np = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        data = get(ep, np)
        batch = data.get("data", [])
        if not batch:
            break
        results.extend(batch)
    return results


def main():
    # Step 1: fetch orders from 04/24 onwards, filter 04/26 client-side
    print(f"Fetching orders since {START}...")
    all_since = paginate("/orders", {"created_at_min": f"{START}T00:00:00Z"})
    window_orders = [
        o for o in all_since
        if (o.get("created_at") or o.get("order_date", ""))[:10] <= END
    ]
    print(f"  {len(window_orders)} orders in {START}–{END}\n")

    if not window_orders:
        print("No orders in window.")
        return

    # Step 2: unique customers
    cust_ids = list({str(o["customer_id"]) for o in window_orders if o.get("customer_id")})
    print(f"  {len(cust_ids)} unique customers\n")

    # Step 3: for each customer, fetch their record (has created_at = their join date)
    for cid in sorted(cust_ids):
        print(f"Customer id={cid}")
        try:
            cdata = get(f"/customers/{cid}")
        except Exception as e:
            print(f"  [error fetching customer] {e}\n")
            continue

        email        = cdata.get("email", "?")
        cust_created = (cdata.get("created_at") or "")[:10]

        # Products bought in the window by this customer
        window_prods = []
        for o in window_orders:
            if str(o.get("customer_id", "")) == cid:
                items = o.get("cart_items") or [{}]
                window_prods.append(items[0].get("product_name", "?"))

        # A customer is "existing" if their account predates the window
        is_existing = bool(cust_created) and cust_created < START
        flag = "*** EXISTING CUSTOMER ***" if is_existing else "NEW"

        print(f"  [{flag}]")
        print(f"  email            : {email}")
        print(f"  customer since   : {cust_created or '?'}")
        print(f"  bought in window : {', '.join(window_prods)}")

        if is_existing:
            print("  --> This customer should NOT be counted as new-to-file.")
        print()

    print("Done.")


if __name__ == "__main__":
    main()
