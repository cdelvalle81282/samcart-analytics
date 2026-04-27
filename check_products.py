"""Check for missing products — compare products table vs what charges/orders reference."""
from cache import SamCartCache

c = SamCartCache()
products = c.get_products_df()
orders = c.get_orders_df()
charges = c.get_charges_df()
subs = c.get_subscriptions_df()
c.conn.close()

print(f"=== Products table: {len(products)} products ===")
for _, p in products.sort_values("name").iterrows():
    print(f"  {p['id']}: {p['name']} (${p['price']:.2f})")

# Products referenced by orders but not in products table
print("\n=== Products in orders but NOT in products table ===")
order_products = orders[["product_id", "product_name"]].drop_duplicates("product_id")
missing_from_products = order_products[~order_products["product_id"].isin(products["id"].astype(str))]
if missing_from_products.empty:
    print("  None — all order products exist in products table")
else:
    for _, r in missing_from_products.iterrows():
        cnt = len(orders[orders["product_id"] == r["product_id"]])
        print(f"  product_id={r['product_id']}: {r['product_name']} ({cnt} orders)")

# Products referenced by subscriptions but not in products table
print("\n=== Products in subscriptions but NOT in products table ===")
sub_products = subs[["product_id", "product_name"]].drop_duplicates("product_id")
missing_from_subs = sub_products[~sub_products["product_id"].isin(products["id"].astype(str))]
if missing_from_subs.empty:
    print("  None — all subscription products exist in products table")
else:
    for _, r in missing_from_subs.iterrows():
        cnt = len(subs[subs["product_id"] == r["product_id"]])
        print(f"  product_id={r['product_id']}: {r['product_name']} ({cnt} subscriptions)")

# Check charges that end up with no product after enrichment
from analytics import enrich_charges_with_product, _is_successful_charge
enriched = enrich_charges_with_product(charges, orders, subs)
no_product = enriched[enriched["product_name"].isna() | (enriched["product_name"] == "")]
if no_product.empty:
    print(f"\n=== All {len(enriched)} charges map to a product ===")
else:
    print(f"\n=== {len(no_product)} charges have NO product mapping ===")
    # Show a sample
    for _, r in no_product.head(10).iterrows():
        print(f"  charge={r['id']} order={r['order_id']} sub={r.get('subscription_id','')} amount=${r['amount']:.2f}")
    if len(no_product) > 10:
        print(f"  ... and {len(no_product) - 10} more")
    # Total revenue missing
    successful_no_prod = no_product[_is_successful_charge(no_product["status"])]
    print(f"  Missing revenue: ${successful_no_prod['amount'].sum():.2f} across {len(successful_no_prod)} successful charges")
