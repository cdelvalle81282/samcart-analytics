"""Pure pandas analytics functions — no DB or API imports."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

# All display dates should be in Eastern time
ET = ZoneInfo("America/New_York")


def _to_eastern(series: pd.Series) -> pd.Series:
    """Convert a UTC datetime series to Eastern time."""
    return pd.to_datetime(series, utc=True).dt.tz_convert(ET)

# Charge status constants
# Note: SamCart API leaves status NULL for successful charges.
# Only refunds get an explicit status value.
SUCCESSFUL_CHARGE_STATUSES = {"charged", "succeeded", "paid", "complete"}
REFUND_CHARGE_STATUSES = {"refunded", "partially_refunded", "refund"}


def _is_successful_charge(status_series: pd.Series) -> pd.Series:
    """A charge is successful if status is NULL/empty OR in the whitelist."""
    lower = status_series.str.lower()
    return lower.isna() | (lower == "") | lower.isin(SUCCESSFUL_CHARGE_STATUSES)


def _is_refund_charge(status_series: pd.Series) -> pd.Series:
    """A charge is a refund if status is in the refund set."""
    return status_series.str.lower().isin(REFUND_CHARGE_STATUSES)


def calculate_customer_ltv(
    orders_df: pd.DataFrame,
    charges_df: pd.DataFrame,
    subscriptions_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Per-customer LTV using charges as source of truth (handles refunds).

    Returns DataFrame with columns:
        customer_email, first_purchase, total_spend, order_count,
        active_subs, estimated_ltv
    """
    if orders_df.empty and charges_df.empty:
        return pd.DataFrame(
            columns=[
                "customer_email", "first_purchase", "total_spend",
                "order_count", "active_subs", "estimated_ltv",
            ]
        )

    # Total spend from successful charges only
    if not charges_df.empty:
        valid_charges = charges_df[
            _is_successful_charge(charges_df["status"])
        ].copy()
        if not valid_charges.empty:
            spend = (
                valid_charges.groupby("customer_email")["amount"]
                .sum()
                .reset_index()
                .rename(columns={"amount": "total_spend"})
            )
        else:
            spend = pd.DataFrame(columns=["customer_email", "total_spend"])
    else:
        # Fallback to orders if no charges table data
        spend = (
            orders_df.groupby("customer_email")["total"]
            .sum()
            .reset_index()
            .rename(columns={"total": "total_spend"})
        )

    # First purchase date and order count from orders
    if not orders_df.empty:
        order_stats = (
            orders_df.groupby("customer_email")
            .agg(first_purchase=("created_at", "min"), order_count=("id", "count"))
            .reset_index()
        )
    else:
        order_stats = pd.DataFrame(
            columns=["customer_email", "first_purchase", "order_count"]
        )

    # Active subscription count
    if not subscriptions_df.empty:
        active = subscriptions_df[
            subscriptions_df["status"].str.lower() == "active"
        ]
        sub_counts = (
            active.groupby("customer_email")["id"]
            .count()
            .reset_index()
            .rename(columns={"id": "active_subs"})
        )
    else:
        sub_counts = pd.DataFrame(columns=["customer_email", "active_subs"])

    # Merge all
    result = order_stats.copy()
    if not spend.empty:
        result = result.merge(spend, on="customer_email", how="outer")
    else:
        result["total_spend"] = 0.0
    if not sub_counts.empty:
        result = result.merge(sub_counts, on="customer_email", how="left")

    result["active_subs"] = result.get("active_subs", 0).fillna(0).astype(int)
    result["total_spend"] = result.get("total_spend", 0.0).fillna(0.0)
    result["order_count"] = result.get("order_count", 0).fillna(0).astype(int)
    result["estimated_ltv"] = result["total_spend"]  # Current realized LTV

    return result.sort_values("total_spend", ascending=False).reset_index(drop=True)


def build_cohort_retention(
    subscriptions_df: pd.DataFrame,
    charges_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Cohort retention analysis.

    Groups subscribers by signup month. For each cohort, tracks % still active
    at month 1, 2, 3, ... N. Active subs are right-censored (counted as
    retained through current month).

    Returns pivot table: rows=cohort month, cols=months since signup, values=retention %.
    """
    if subscriptions_df.empty:
        return pd.DataFrame()

    subs = subscriptions_df.copy()
    subs["created_at"] = _to_eastern(subs["created_at"])
    subs = subs.dropna(subset=["created_at"])

    if subs.empty:
        return pd.DataFrame()

    # Assign cohort (Eastern time)
    subs["cohort"] = subs["created_at"].dt.to_period("M")

    # Determine end date per subscription
    now = pd.Timestamp(datetime.now(ET))
    subs["canceled_at"] = pd.to_datetime(subs["canceled_at"], utc=True).dt.tz_convert(ET)
    subs["end_date"] = subs["canceled_at"].fillna(now)

    # Calculate months active
    subs["months_active"] = (
        (subs["end_date"].dt.to_period("M") - subs["cohort"])
        .apply(lambda x: max(x.n, 0) if pd.notna(x) else 0)
    )

    # Build retention matrix
    cohorts = subs.groupby("cohort")

    # Find the max number of periods
    max_periods = int(subs["months_active"].max()) + 1 if not subs["months_active"].isna().all() else 1
    max_periods = min(max_periods, 24)  # Cap at 24 months for display

    retention_data = []
    for cohort, group in cohorts:
        size = len(group)
        if size == 0:
            continue
        row = {"cohort": str(cohort), "cohort_size": size}
        for period in range(max_periods):
            active_count = (group["months_active"] >= period).sum()
            row[period] = active_count / size * 100
        retention_data.append(row)

    if not retention_data:
        return pd.DataFrame()

    result = pd.DataFrame(retention_data)
    result = result.set_index("cohort")

    return result


def product_ltv_ranking(
    orders_df: pd.DataFrame,
    subscriptions_df: pd.DataFrame,
    products_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Per-product revenue ranking.

    Groups by product_id, displays latest product name.
    Returns: product_id, product_name, total_revenue, order_count,
             avg_order_value, subscriber_count, avg_lifetime_months.
    """
    if orders_df.empty:
        return pd.DataFrame(
            columns=[
                "product_id", "product_name", "total_revenue", "order_count",
                "avg_order_value", "subscriber_count", "avg_lifetime_months",
            ]
        )

    # Revenue and order stats by product_id
    order_stats = (
        orders_df.groupby("product_id")
        .agg(total_revenue=("total", "sum"), order_count=("id", "count"))
        .reset_index()
    )
    order_stats["avg_order_value"] = (
        order_stats["total_revenue"] / order_stats["order_count"]
    )

    # Product names — prefer products table (latest name), fallback to orders
    if not products_df.empty:
        name_map = products_df.set_index("id")["name"].to_dict()
    else:
        name_map = {}

    # Fallback from orders for any missing product names
    order_names = orders_df.drop_duplicates("product_id", keep="last").set_index("product_id")["product_name"].to_dict()
    for pid in order_stats["product_id"]:
        if pid not in name_map:
            name_map[pid] = order_names.get(pid, f"Product {pid}")

    order_stats["product_name"] = order_stats["product_id"].map(name_map).fillna("Unknown")

    # Subscription stats by product
    if not subscriptions_df.empty:
        subs = subscriptions_df.copy()
        subs["created_at"] = _to_eastern(subs["created_at"])
        subs["canceled_at"] = pd.to_datetime(subs["canceled_at"], utc=True).dt.tz_convert(ET)
        now = pd.Timestamp(datetime.now(ET))
        subs["end_date"] = subs["canceled_at"].fillna(now)
        subs["lifetime_months"] = (
            (subs["end_date"] - subs["created_at"]).dt.days / 30.44
        ).clip(lower=0)

        sub_stats = (
            subs.groupby("product_id")
            .agg(subscriber_count=("id", "count"), avg_lifetime_months=("lifetime_months", "mean"))
            .reset_index()
        )
        order_stats = order_stats.merge(sub_stats, on="product_id", how="left")
    else:
        order_stats["subscriber_count"] = 0
        order_stats["avg_lifetime_months"] = 0.0

    order_stats["subscriber_count"] = order_stats["subscriber_count"].fillna(0).astype(int)
    order_stats["avg_lifetime_months"] = order_stats["avg_lifetime_months"].fillna(0.0).round(1)

    return order_stats.sort_values("total_revenue", ascending=False).reset_index(drop=True)


def monthly_revenue_summary(
    orders_df: pd.DataFrame,
    charges_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Monthly revenue (from successful charges) and order count.

    Returns: month, total_revenue, order_count.
    """
    if orders_df.empty and (charges_df is None or charges_df.empty):
        return pd.DataFrame(columns=["month", "total_revenue", "order_count"])

    # Order count from orders table
    order_counts = pd.DataFrame(columns=["month", "order_count"])
    if not orders_df.empty:
        odf = orders_df.copy()
        odf["created_at"] = _to_eastern(odf["created_at"])
        odf = odf.dropna(subset=["created_at"])
        if not odf.empty:
            odf["month"] = odf["created_at"].dt.to_period("M").astype(str)
            order_counts = (
                odf.groupby("month")
                .agg(order_count=("id", "count"))
                .reset_index()
            )

    # Revenue from successful charges (source of truth)
    if charges_df is not None and not charges_df.empty:
        cdf = charges_df.copy()
        cdf = cdf[_is_successful_charge(cdf["status"])]
        cdf["created_at"] = _to_eastern(cdf["created_at"])
        cdf = cdf.dropna(subset=["created_at"])
        if not cdf.empty:
            cdf["month"] = cdf["created_at"].dt.to_period("M").astype(str)
            revenue = (
                cdf.groupby("month")
                .agg(total_revenue=("amount", "sum"))
                .reset_index()
            )
        else:
            revenue = pd.DataFrame(columns=["month", "total_revenue"])
    else:
        # Fallback to orders if no charges available
        if not orders_df.empty:
            odf2 = orders_df.copy()
            odf2["created_at"] = _to_eastern(odf2["created_at"])
            odf2 = odf2.dropna(subset=["created_at"])
            odf2["month"] = odf2["created_at"].dt.to_period("M").astype(str)
            revenue = (
                odf2.groupby("month")
                .agg(total_revenue=("total", "sum"))
                .reset_index()
            )
        else:
            revenue = pd.DataFrame(columns=["month", "total_revenue"])

    # Merge order counts and revenue
    if order_counts.empty and revenue.empty:
        return pd.DataFrame(columns=["month", "total_revenue", "order_count"])

    result = revenue.merge(order_counts, on="month", how="outer")
    result["total_revenue"] = result["total_revenue"].fillna(0.0)
    result["order_count"] = result["order_count"].fillna(0).astype(int)

    return result.sort_values("month").reset_index(drop=True)


# ------------------------------------------------------------------
# Daily metrics helpers and functions
# ------------------------------------------------------------------


def enrich_charges_with_product(
    charges_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    subscriptions_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add product_id and product_name to charges by joining orders and subscriptions.

    Prefers order-derived product info, falls back to subscription-derived.
    """
    df = charges_df.copy()

    # Join via order_id (charges.order_id → orders.id)
    if not orders_df.empty and "order_id" in df.columns and "id" in orders_df.columns:
        order_products = (
            orders_df[["id", "product_id", "product_name"]]
            .drop_duplicates("id", keep="last")
            .rename(columns={"id": "order_id", "product_id": "o_product_id", "product_name": "o_product_name"})
        )
        # Ensure matching dtypes
        df["order_id"] = df["order_id"].astype(str)
        order_products["order_id"] = order_products["order_id"].astype(str)
        df = df.merge(order_products, on="order_id", how="left")
    else:
        df["o_product_id"] = pd.NA
        df["o_product_name"] = pd.NA

    # Join via subscription_id
    if (
        not subscriptions_df.empty
        and "subscription_id" in df.columns
        and "id" in subscriptions_df.columns
    ):
        sub_products = (
            subscriptions_df[["id", "product_id", "product_name"]]
            .drop_duplicates("id", keep="last")
            .rename(columns={
                "id": "subscription_id",
                "product_id": "s_product_id",
                "product_name": "s_product_name",
            })
        )
        df["subscription_id"] = df["subscription_id"].astype(str)
        sub_products["subscription_id"] = sub_products["subscription_id"].astype(str)
        df = df.merge(sub_products, on="subscription_id", how="left")
    else:
        df["s_product_id"] = pd.NA
        df["s_product_name"] = pd.NA

    # Coalesce: prefer order-derived, fall back to subscription-derived
    df["product_id"] = df["o_product_id"].fillna(df["s_product_id"])
    df["product_name"] = df["o_product_name"].fillna(df["s_product_name"])
    df = df.drop(columns=["o_product_id", "o_product_name", "s_product_id", "s_product_name"])

    return df


def _identify_renewals(charges_df: pd.DataFrame) -> pd.Series:
    """
    Return a boolean Series: True for renewal charges, False for initial purchases.

    For each subscription_id, ranks charges by created_at. Rank > 1 = renewal.
    Charges with no subscription_id are never renewals.
    """
    result = pd.Series(False, index=charges_df.index)

    if "subscription_id" not in charges_df.columns:
        return result

    has_sub = charges_df["subscription_id"].notna() & (charges_df["subscription_id"] != "") & (charges_df["subscription_id"] != "nan")

    if has_sub.any():
        sub_charges = charges_df.loc[has_sub].copy()
        sub_charges["created_at"] = pd.to_datetime(sub_charges["created_at"], errors="coerce")
        sub_charges["rank"] = sub_charges.groupby("subscription_id")["created_at"].rank(method="first")
        result.loc[sub_charges.index] = sub_charges["rank"] > 1

    return result


def daily_new_to_file(orders_df: pd.DataFrame) -> pd.DataFrame:
    """
    Daily new-to-file customers by product.

    A customer is new-to-file on the date of their very first purchase
    across ALL products.

    Returns: date, product_id, product_name, new_customer_count
    """
    cols = ["date", "product_id", "product_name", "new_customer_count"]
    if orders_df.empty:
        return pd.DataFrame(columns=cols)

    df = orders_df.copy()
    df["created_at"] = _to_eastern(df["created_at"])
    df = df.dropna(subset=["created_at"])
    if df.empty:
        return pd.DataFrame(columns=cols)

    df["date"] = df["created_at"].dt.date

    # Each customer's first purchase date (across all products)
    first_purchase = df.groupby("customer_email")["date"].min().reset_index()
    first_purchase.columns = ["customer_email", "first_date"]

    df = df.merge(first_purchase, on="customer_email", how="left")
    new_customers = df[df["date"] == df["first_date"]]

    result = (
        new_customers.groupby(["date", "product_id", "product_name"])["customer_email"]
        .nunique()
        .reset_index()
        .rename(columns={"customer_email": "new_customer_count"})
    )
    return result


def daily_new_sales(
    charges_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    subscriptions_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Daily new sales (initial purchases + one-time charges) by product.

    Excludes renewals. Uses successful charges only.
    Returns: date, product_id, product_name, sale_count, sale_revenue
    """
    cols = ["date", "product_id", "product_name", "sale_count", "sale_revenue"]
    if charges_df.empty:
        return pd.DataFrame(columns=cols)

    df = charges_df.copy()
    df = df[_is_successful_charge(df["status"])]
    if df.empty:
        return pd.DataFrame(columns=cols)

    df = enrich_charges_with_product(df, orders_df, subscriptions_df)
    df["created_at"] = _to_eastern(df["created_at"])
    df = df.dropna(subset=["created_at"])
    df["date"] = df["created_at"].dt.date

    # Exclude renewals
    is_renewal = _identify_renewals(df)
    df = df[~is_renewal]

    if df.empty:
        return pd.DataFrame(columns=cols)

    result = (
        df.groupby(["date", "product_id", "product_name"])
        .agg(sale_count=("amount", "count"), sale_revenue=("amount", "sum"))
        .reset_index()
    )
    return result


def daily_refunds(
    charges_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    subscriptions_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Daily refunds by product.

    Returns: date, product_id, product_name, refund_count, refund_amount
    """
    cols = ["date", "product_id", "product_name", "refund_count", "refund_amount"]
    if charges_df.empty:
        return pd.DataFrame(columns=cols)

    df = charges_df.copy()
    df = df[_is_refund_charge(df["status"])]
    if df.empty:
        return pd.DataFrame(columns=cols)

    df = enrich_charges_with_product(df, orders_df, subscriptions_df)
    df["created_at"] = _to_eastern(df["created_at"])
    df = df.dropna(subset=["created_at"])
    df["date"] = df["created_at"].dt.date

    result = (
        df.groupby(["date", "product_id", "product_name"])
        .agg(refund_count=("amount", "count"), refund_amount=("amount", "sum"))
        .reset_index()
    )
    return result


def daily_renewals(
    charges_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    subscriptions_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Daily renewal charges by product.

    Returns: date, product_id, product_name, renewal_count, renewal_revenue
    """
    cols = ["date", "product_id", "product_name", "renewal_count", "renewal_revenue"]
    if charges_df.empty:
        return pd.DataFrame(columns=cols)

    df = charges_df.copy()
    df = df[_is_successful_charge(df["status"])]
    if df.empty:
        return pd.DataFrame(columns=cols)

    # Must have subscription_id
    if "subscription_id" not in df.columns:
        return pd.DataFrame(columns=cols)

    df = df[df["subscription_id"].notna() & (df["subscription_id"] != "") & (df["subscription_id"] != "nan")]
    if df.empty:
        return pd.DataFrame(columns=cols)

    df = enrich_charges_with_product(df, orders_df, subscriptions_df)
    df["created_at"] = _to_eastern(df["created_at"])
    df = df.dropna(subset=["created_at"])
    df["date"] = df["created_at"].dt.date

    # Keep only renewals (rank > 1)
    is_renewal = _identify_renewals(df)
    df = df[is_renewal]

    if df.empty:
        return pd.DataFrame(columns=cols)

    result = (
        df.groupby(["date", "product_id", "product_name"])
        .agg(renewal_count=("amount", "count"), renewal_revenue=("amount", "sum"))
        .reset_index()
    )
    return result


def build_daily_summary(
    orders_df: pd.DataFrame,
    charges_df: pd.DataFrame,
    subscriptions_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Combined daily summary: new customers, new sales, refunds, renewals.

    Returns flat table with all metrics merged on [date, product_id, product_name].
    """
    ntf = daily_new_to_file(orders_df)
    ns = daily_new_sales(charges_df, orders_df, subscriptions_df)
    ref = daily_refunds(charges_df, orders_df, subscriptions_df)
    ren = daily_renewals(charges_df, orders_df, subscriptions_df)

    merge_keys = ["date", "product_id", "product_name"]

    result = ntf
    for right in [ns, ref, ren]:
        if right.empty:
            continue
        if result.empty:
            result = right
        else:
            result = result.merge(right, on=merge_keys, how="outer")

    if result.empty:
        return pd.DataFrame(columns=[
            "date", "product_id", "product_name",
            "new_customer_count", "sale_count", "sale_revenue",
            "refund_count", "refund_amount", "renewal_count", "renewal_revenue",
        ])

    fill_cols = [
        "new_customer_count", "sale_count", "sale_revenue",
        "refund_count", "refund_amount", "renewal_count", "renewal_revenue",
    ]
    for col in fill_cols:
        if col in result.columns:
            result[col] = result[col].fillna(0)
        else:
            result[col] = 0

    result["date"] = pd.to_datetime(result["date"])
    return result.sort_values(["date", "product_name"]).reset_index(drop=True)


def new_customer_ltv_by_entry_product(
    orders_df: pd.DataFrame,
    charges_df: pd.DataFrame,
    subscriptions_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    LTV analysis grouped by each customer's entry product (first purchase).

    Returns: product_id, product_name, customer_count, avg_ltv, median_ltv, total_ltv
    """
    cols = ["product_id", "product_name", "customer_count", "avg_ltv", "median_ltv", "total_ltv"]
    if orders_df.empty:
        return pd.DataFrame(columns=cols)

    odf = orders_df.copy()
    odf["created_at"] = _to_eastern(odf["created_at"])
    odf = odf.dropna(subset=["created_at"])
    if odf.empty:
        return pd.DataFrame(columns=cols)

    # Find each customer's first order -> entry product
    first_order_idx = odf.groupby("customer_email")["created_at"].idxmin()
    first_orders = odf.loc[first_order_idx, ["customer_email", "product_id", "product_name"]]
    first_orders = first_orders.rename(columns={
        "product_id": "entry_product_id",
        "product_name": "entry_product_name",
    })

    # Total spend per customer from successful charges
    if not charges_df.empty:
        valid = charges_df[_is_successful_charge(charges_df["status"])].copy()
        if not valid.empty:
            spend = (
                valid.groupby("customer_email")["amount"]
                .sum()
                .reset_index()
                .rename(columns={"amount": "total_spend"})
            )
        else:
            spend = pd.DataFrame(columns=["customer_email", "total_spend"])
    else:
        spend = (
            odf.groupby("customer_email")["total"]
            .sum()
            .reset_index()
            .rename(columns={"total": "total_spend"})
        )

    merged = first_orders.merge(spend, on="customer_email", how="left")
    merged["total_spend"] = merged["total_spend"].fillna(0.0)

    result = (
        merged.groupby(["entry_product_id", "entry_product_name"])
        .agg(
            customer_count=("customer_email", "count"),
            avg_ltv=("total_spend", "mean"),
            median_ltv=("total_spend", "median"),
            total_ltv=("total_spend", "sum"),
        )
        .reset_index()
        .rename(columns={"entry_product_id": "product_id", "entry_product_name": "product_name"})
    )

    return result.sort_values("total_ltv", ascending=False).reset_index(drop=True)
