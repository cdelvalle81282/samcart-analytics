"""Pure pandas analytics functions — no DB or API imports."""

from datetime import datetime, timezone

import pandas as pd


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
            charges_df["status"].str.lower().isin(["charged", "succeeded", "paid", "complete"])
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
    subs["created_at"] = pd.to_datetime(subs["created_at"], errors="coerce")
    subs = subs.dropna(subset=["created_at"])

    if subs.empty:
        return pd.DataFrame()

    # Assign cohort
    subs["cohort"] = subs["created_at"].dt.to_period("M")

    # Determine end date per subscription
    now = pd.Timestamp(datetime.now(timezone.utc))
    subs["canceled_at"] = pd.to_datetime(subs["canceled_at"], errors="coerce")
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
        subs["created_at"] = pd.to_datetime(subs["created_at"], errors="coerce")
        subs["canceled_at"] = pd.to_datetime(subs["canceled_at"], errors="coerce")
        now = pd.Timestamp(datetime.now(timezone.utc))
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


def monthly_revenue_summary(orders_df: pd.DataFrame) -> pd.DataFrame:
    """
    Monthly total revenue and order count.

    Returns: month, total_revenue, order_count.
    """
    if orders_df.empty:
        return pd.DataFrame(columns=["month", "total_revenue", "order_count"])

    df = orders_df.copy()
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df = df.dropna(subset=["created_at"])

    if df.empty:
        return pd.DataFrame(columns=["month", "total_revenue", "order_count"])

    df["month"] = df["created_at"].dt.to_period("M").astype(str)

    result = (
        df.groupby("month")
        .agg(total_revenue=("total", "sum"), order_count=("id", "count"))
        .reset_index()
        .sort_values("month")
    )

    return result
