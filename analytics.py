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
    lower = status_series.fillna("").str.lower().str.strip()
    return lower.isin(SUCCESSFUL_CHARGE_STATUSES) | (lower == "")


def _is_refund_charge(status_series: pd.Series) -> pd.Series:
    """A charge is a refund if status is in the refund set."""
    return status_series.str.lower().isin(REFUND_CHARGE_STATUSES)


# Collected = money was collected (includes partially refunded at reduced amount)
COLLECTED_CHARGE_STATUSES = SUCCESSFUL_CHARGE_STATUSES | {"partially_refunded"}


def _is_collected_charge(status_series: pd.Series) -> pd.Series:
    """True for charges that collected money (successful + partially refunded)."""
    s = status_series.fillna("").str.lower().str.strip()
    return s.isin(COLLECTED_CHARGE_STATUSES) | (s == "")


def _is_gross_charge(status_series: pd.Series) -> pd.Series:
    """True for charges that transacted (successful + refunded). Excludes failed/pending."""
    return _is_successful_charge(status_series) | _is_refund_charge(status_series)


def _net_charge_amount(df: pd.DataFrame) -> pd.Series:
    """Net realized revenue per charge: amount minus refund for collected charges."""
    amount = df["amount"].fillna(0)
    refund = df["refund_amount"].fillna(0) if "refund_amount" in df.columns else pd.Series(0, index=df.index)
    is_collected = _is_collected_charge(df["status"])
    net = pd.Series(0.0, index=df.index)
    net[is_collected] = amount[is_collected] - refund[is_collected]
    return net.clip(lower=0)


def _refund_charge_amount(df: pd.DataFrame) -> pd.Series:
    """
    Effective refunded dollars per charge.

    Full refunds fall back to the original charge amount when refund_amount is
    absent or zero. Partial refunds only use the explicit refund_amount.
    """
    amount = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    refund = (
        pd.to_numeric(df["refund_amount"], errors="coerce")
        if "refund_amount" in df.columns
        else pd.Series(pd.NA, index=df.index, dtype="float64")
    )
    status = df["status"].fillna("").str.lower().str.strip()
    effective = refund.fillna(0).clip(lower=0)
    full_refunds = status.isin({"refunded", "refund"})
    effective.loc[full_refunds] = refund.loc[full_refunds].where(
        refund.loc[full_refunds].fillna(0) > 0,
        amount.loc[full_refunds],
    ).clip(lower=0)
    return effective


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

    # Total spend from collected charges (net of partial refunds)
    if not charges_df.empty:
        valid_charges = charges_df[
            _is_collected_charge(charges_df["status"])
        ].copy()
        if not valid_charges.empty:
            valid_charges["net_amount"] = _net_charge_amount(valid_charges)
            spend = (
                valid_charges.groupby("customer_email")["net_amount"]
                .sum()
                .reset_index()
                .rename(columns={"net_amount": "total_spend"})
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


def build_cohort_performance(
    charges_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    subscriptions_df: pd.DataFrame,
    *,
    product_filter: str | None = None,
    interval_filter: str | None = None,

) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Charge-based cohort performance analysis for subscription charges.

    Returns a tuple of three DataFrames:
        (activity_summary, renewal_rates, stick_rates)

    For each subscription, charges are ranked by created_at ascending.
    Rank 1 = Period 0 (initial purchase), Rank 2+ = renewal periods.
    Only charges linked to a subscription_id are included.
    """
    # Column definitions for empty returns
    activity_cols = [
        "period", "active_subscribers", "renewals", "initial_charges",
        "total_charged", "cumulative_refunds", "refunds_this_period",
        "period_revenue", "cumulative_revenue",
    ]
    renewal_cols = [
        "period", "subscribers_start", "subscribers_end",
        "dropped_off", "renewal_rate", "stick_rate", "notes",
    ]
    stick_cols = [
        "period", "original_cohort", "still_active",
        "dropped_cumulative", "stick_rate", "cumulative_refunds",
        "refund_rate", "churn_refund_rate",
    ]
    empty_activity = pd.DataFrame(columns=activity_cols)
    empty_renewal = pd.DataFrame(columns=renewal_cols)
    empty_stick = pd.DataFrame(columns=stick_cols)

    if charges_df.empty:
        return empty_activity, empty_renewal, empty_stick

    # --- 1. Filter to subscription-linked charges only ---
    df = charges_df.copy()
    df = df[df["subscription_id"].notna()]
    df["subscription_id"] = df["subscription_id"].astype(str).str.strip()
    df = df[df["subscription_id"].ne("") & df["subscription_id"].ne("nan")]
    if df.empty:
        return empty_activity, empty_renewal, empty_stick

    # --- 2. Enrich charges with product info ---
    df = enrich_charges_with_product(df, orders_df, subscriptions_df)

    # --- 3. Join interval from subscriptions table ---
    if (
        not subscriptions_df.empty
        and "id" in subscriptions_df.columns
        and "interval" in subscriptions_df.columns
    ):
        interval_map = (
            subscriptions_df[["id", "interval"]]
            .drop_duplicates("id", keep="last")
            .rename(columns={"id": "subscription_id"})
        )
        interval_map["subscription_id"] = interval_map["subscription_id"].astype(str)
        df["subscription_id"] = df["subscription_id"].astype(str)
        df = df.merge(interval_map, on="subscription_id", how="left", suffixes=("", "_sub"))
        # If interval came from subscriptions, prefer it
        if "interval_sub" in df.columns:
            df["interval"] = df["interval_sub"].fillna(df.get("interval", pd.NA))
            df = df.drop(columns=["interval_sub"])
    else:
        if "interval" not in df.columns:
            df["interval"] = pd.NA

    # --- 4. Apply product/interval filters ---
    if product_filter:
        df = df[df["product_id"].astype(str) == str(product_filter)]
    if interval_filter:
        df = df[df["interval"].astype(str).str.lower() == interval_filter.lower()]
    if df.empty:
        return empty_activity, empty_renewal, empty_stick

    # --- 5. Classify charges ---
    df["is_successful"] = _is_successful_charge(df["status"])
    df["is_refund"] = _is_refund_charge(df["status"])

    # --- 6. Rank charges per subscription by created_at ascending ---
    df["created_at_ts"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
    df = df.dropna(subset=["created_at_ts"])
    df = df.sort_values(["subscription_id", "created_at_ts"])
    df["rank"] = df.groupby("subscription_id").cumcount() + 1
    df["period"] = df["rank"] - 1  # Rank 1 = Period 0

    # --- 7. Compute net revenue ---
    df["net_amount"] = _net_charge_amount(df)

    # --- 8. Build activity summary ---
    periods = sorted(df["period"].unique())

    activity_rows = []
    for period in periods:
        period_df = df[df["period"] == period]
        successful_df = period_df[period_df["is_successful"]]
        refund_df = period_df[period_df["is_refund"]]

        active_subs = successful_df["subscription_id"].nunique()
        refunds_this = refund_df["subscription_id"].nunique()
        # total_charged = unique subs with a successful OR refunded charge
        charged_subs = period_df[
            period_df["is_successful"] | period_df["is_refund"]
        ]["subscription_id"].nunique()
        period_revenue = successful_df["net_amount"].sum()

        activity_rows.append({
            "period": period,
            "active_subscribers": active_subs,
            "renewals": active_subs if period > 0 else 0,
            "initial_charges": active_subs if period == 0 else 0,
            "total_charged": charged_subs,
            "refunds_this_period": refunds_this,
            "period_revenue": period_revenue,
        })

    activity = pd.DataFrame(activity_rows)

    # Cumulative columns
    activity["cumulative_refunds"] = activity["refunds_this_period"].cumsum()
    activity["cumulative_revenue"] = activity["period_revenue"].cumsum()

    # --- 9. Build renewal rates (periods > 0 only) ---
    cohort_size = activity.loc[activity["period"] == 0, "active_subscribers"].iloc[0]

    renewal_rows = []
    for i, period in enumerate(periods):
        if period == 0:
            continue
        prev_period = periods[i - 1]
        start = activity.loc[
            activity["period"] == prev_period, "active_subscribers"
        ].iloc[0]
        end = activity.loc[
            activity["period"] == period, "active_subscribers"
        ].iloc[0]
        dropped = start - end
        rate = (end / start * 100) if start > 0 else 0.0
        stick = (end / cohort_size * 100) if cohort_size > 0 else 0.0
        renewal_rows.append({
            "period": period,
            "subscribers_start": start,
            "subscribers_end": end,
            "dropped_off": dropped,
            "renewal_rate": rate,
            "stick_rate": stick,
            "notes": "",
        })

    renewal = pd.DataFrame(renewal_rows)
    if not renewal.empty:
        max_drop_idx = renewal["dropped_off"].idxmax()
        renewal.loc[max_drop_idx, "notes"] = "Largest period-over-period drop"

    # --- 10. Build stick rates (all periods) ---
    stick_rows = []
    cum_refunds = 0
    for _, row in activity.iterrows():
        period = row["period"]
        still_active = row["active_subscribers"]
        cum_refunds += row["refunds_this_period"]
        dropped_cum = cohort_size - still_active
        s_rate = (still_active / cohort_size * 100) if cohort_size > 0 else 0.0
        r_rate = (cum_refunds / cohort_size * 100) if cohort_size > 0 else 0.0
        cr_rate = (
            ((dropped_cum + cum_refunds) / cohort_size * 100)
            if cohort_size > 0 else 0.0
        )
        stick_rows.append({
            "period": period,
            "original_cohort": cohort_size,
            "still_active": still_active,
            "dropped_cumulative": dropped_cum,
            "stick_rate": s_rate,
            "cumulative_refunds": cum_refunds,
            "refund_rate": r_rate,
            "churn_refund_rate": cr_rate,
        })

    stick_df = pd.DataFrame(stick_rows)

    return activity, renewal, stick_df


def build_cohort_heatmap(
    charges_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    subscriptions_df: pd.DataFrame,
    *,
    product_filter: str | None = None,
    interval_filter: str | None = None,
) -> pd.DataFrame:
    """
    Per-period cohort retention heatmap based on actual charges.

    For each subscription, charges are ranked by created_at ascending.
    Period 0 = initial charge; period 1, 2, ... = renewals.
    Cohort = calendar month (Eastern time) of the period-0 charge.

    Returns a pivot table:
        index = cohort month string (e.g. "2024-01")
        columns = "cohort_size" + integer period columns (0, 1, 2, ...)
        values = retention % (% of cohort subs with a successful charge at that period)
        index.name = "cohort"

    Returns empty DataFrame if no qualifying data.
    """
    if charges_df.empty:
        return pd.DataFrame()

    # --- 1. Filter to subscription-linked charges ---
    df = charges_df.copy()
    df = df[df["subscription_id"].notna()]
    df["subscription_id"] = df["subscription_id"].astype(str).str.strip()
    df = df[df["subscription_id"].ne("") & df["subscription_id"].ne("nan")]
    if df.empty:
        return pd.DataFrame()

    # --- 2. Enrich with product info ---
    df = enrich_charges_with_product(df, orders_df, subscriptions_df)

    # --- 3. Join interval from subscriptions table ---
    if (
        not subscriptions_df.empty
        and "id" in subscriptions_df.columns
        and "interval" in subscriptions_df.columns
    ):
        interval_map = (
            subscriptions_df[["id", "interval"]]
            .drop_duplicates("id", keep="last")
            .rename(columns={"id": "subscription_id"})
        )
        interval_map["subscription_id"] = interval_map["subscription_id"].astype(str)
        df["subscription_id"] = df["subscription_id"].astype(str)
        df = df.merge(interval_map, on="subscription_id", how="left", suffixes=("", "_sub"))
        if "interval_sub" in df.columns:
            df["interval"] = df["interval_sub"].fillna(df.get("interval", pd.NA))
            df = df.drop(columns=["interval_sub"])
    else:
        if "interval" not in df.columns:
            df["interval"] = pd.NA

    # --- 4. Apply product/interval filters ---
    if product_filter:
        df = df[df["product_id"].astype(str) == str(product_filter)]
    if interval_filter:
        df = df[df["interval"].astype(str).str.lower() == interval_filter.lower()]
    if df.empty:
        return pd.DataFrame()

    # --- 5. Classify successful charges ---
    df["is_successful"] = _is_successful_charge(df["status"])

    # --- 6. Parse dates and drop NaT ---
    df["created_at_ts"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
    df = df.dropna(subset=["created_at_ts"])
    if df.empty:
        return pd.DataFrame()

    # --- 7. Rank charges per subscription by created_at (period 0, 1, 2, ...) ---
    df = df.sort_values(["subscription_id", "created_at_ts"])
    df["period"] = df.groupby("subscription_id").cumcount()  # 0-based

    # Cap max periods at 52
    df = df[df["period"] <= 52]

    # --- 8. Determine cohort = month of period-0 charge (Eastern time) ---
    period0 = df[df["period"] == 0][["subscription_id", "created_at_ts"]].copy()
    period0["cohort_period"] = (
        period0["created_at_ts"].dt.tz_convert(ET).dt.to_period("M")
    )
    period0 = period0[["subscription_id", "cohort_period"]]
    df = df.merge(period0, on="subscription_id", how="left")
    df = df.dropna(subset=["cohort_period"])
    if df.empty:
        return pd.DataFrame()

    # --- 9. For each cohort, track % of subs with a successful charge at each period ---
    # Only count successful charges for retention
    successful = df[df["is_successful"]]

    # Cohort sizes: count of unique subs per cohort
    cohort_subs = df.drop_duplicates("subscription_id")[["subscription_id", "cohort_period"]]
    cohort_sizes = cohort_subs.groupby("cohort_period")["subscription_id"].nunique()

    # For each cohort+period, count unique subs with a successful charge
    retention = (
        successful.groupby(["cohort_period", "period"])["subscription_id"]
        .nunique()
        .reset_index(name="active_count")
    )

    # --- 10. Build pivot table ---
    cohorts_sorted = sorted(cohort_sizes.index)
    max_period = int(df["period"].max()) if not df["period"].isna().all() else 0
    max_period = min(max_period, 52)

    rows = []
    for cohort in cohorts_sorted:
        size = cohort_sizes[cohort]
        if size == 0:
            continue
        row = {"cohort": str(cohort), "cohort_size": size}
        cohort_retention = retention[retention["cohort_period"] == cohort]
        for period in range(max_period + 1):
            match = cohort_retention[cohort_retention["period"] == period]
            if not match.empty:
                row[period] = match["active_count"].iloc[0] / size * 100
            else:
                row[period] = 0.0
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows).set_index("cohort")
    result.index.name = "cohort"

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

    # Revenue from collected charges — net of partial refunds (source of truth)
    if charges_df is not None and not charges_df.empty:
        cdf = charges_df.copy()
        cdf = cdf[_is_collected_charge(cdf["status"])]
        cdf["created_at"] = _to_eastern(cdf["created_at"])
        cdf = cdf.dropna(subset=["created_at"])
        if not cdf.empty:
            cdf["net_amount"] = _net_charge_amount(cdf)
            cdf["month"] = cdf["created_at"].dt.to_period("M").astype(str)
            revenue = (
                cdf.groupby("month")
                .agg(total_revenue=("net_amount", "sum"))
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


def _identify_renewals(
    charges_df: pd.DataFrame,
    subscriptions_df: pd.DataFrame | None = None,
) -> pd.Series:
    """
    Return a boolean Series: True for renewal charges, False for initial purchases.

    For each subscription_id, ranks charges by created_at. Rank > 1 = renewal.
    Charges with no subscription_id are never renewals.

    Additionally, if a rank-1 charge's subscription was created more than 48 hours
    before the charge, it is treated as a renewal. This handles cases where older
    charges were not synced and the earliest charge in the DB is not truly the first.
    """
    result = pd.Series(False, index=charges_df.index)

    if "subscription_id" not in charges_df.columns:
        return result

    has_sub = charges_df["subscription_id"].notna() & (charges_df["subscription_id"] != "") & (charges_df["subscription_id"] != "nan")

    if has_sub.any():
        sub_charges = charges_df.loc[has_sub].copy()
        sub_charges["_charge_dt"] = pd.to_datetime(sub_charges["created_at"], errors="coerce")
        sub_charges["rank"] = sub_charges.groupby("subscription_id")["_charge_dt"].rank(method="first")
        is_ranked_renewal = sub_charges["rank"] > 1

        # For rank-1 charges, check if the subscription predates the charge
        if subscriptions_df is not None and not subscriptions_df.empty:
            rank1_mask = sub_charges["rank"] == 1
            if rank1_mask.any():
                rank1 = sub_charges.loc[rank1_mask].copy()
                rank1["_orig_idx"] = rank1.index
                sub_dates = (
                    subscriptions_df[["id", "created_at"]]
                    .drop_duplicates("id", keep="last")
                    .rename(columns={"id": "subscription_id", "created_at": "_sub_created"})
                )
                sub_dates["subscription_id"] = sub_dates["subscription_id"].astype(str)
                rank1["subscription_id"] = rank1["subscription_id"].astype(str)
                rank1 = rank1.merge(sub_dates, on="subscription_id", how="left")
                rank1["_sub_created_dt"] = pd.to_datetime(rank1["_sub_created"], errors="coerce", utc=True)
                charge_dt = rank1["_charge_dt"]
                if charge_dt.dt.tz is None:
                    charge_dt = charge_dt.dt.tz_localize("UTC")
                else:
                    charge_dt = charge_dt.dt.tz_convert("UTC")
                age = charge_dt - rank1["_sub_created_dt"]
                old_sub_idx = rank1.loc[age > pd.Timedelta(hours=48), "_orig_idx"]
                is_ranked_renewal.loc[old_sub_idx] = True

        result.loc[sub_charges.index] = is_ranked_renewal

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
    df = df[_is_collected_charge(df["status"])]
    if df.empty:
        return pd.DataFrame(columns=cols)

    df = enrich_charges_with_product(df, orders_df, subscriptions_df)
    df["net_amount"] = _net_charge_amount(df)
    df["created_at"] = _to_eastern(df["created_at"])
    df = df.dropna(subset=["created_at"])
    df["date"] = df["created_at"].dt.date

    # Exclude renewals
    is_renewal = _identify_renewals(df, subscriptions_df)
    df = df[~is_renewal]

    if df.empty:
        return pd.DataFrame(columns=cols)

    result = (
        df.groupby(["date", "product_id", "product_name"])
        .agg(sale_count=("net_amount", "count"), sale_revenue=("net_amount", "sum"))
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

    Uses refund_date (when available) for the date axis, and refund_amount
    (falling back to charge amount for full refunds missing explicit refund_amount).
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

    df["_effective_refund"] = _refund_charge_amount(df)

    # Prefer refund_date for the date axis; fall back to created_at
    if "refund_date" in df.columns and df["refund_date"].notna().any():
        df["_event_date"] = pd.to_datetime(df["refund_date"], errors="coerce", utc=True)
        # Fall back to created_at where refund_date is missing
        fallback = _to_eastern(df["created_at"])
        df["_event_date"] = df["_event_date"].fillna(fallback)
        df["_event_date"] = df["_event_date"].dt.tz_convert(ET)
    else:
        df["_event_date"] = _to_eastern(df["created_at"])

    df = df.dropna(subset=["_event_date"])
    df["date"] = df["_event_date"].dt.date

    result = (
        df.groupby(["date", "product_id", "product_name"])
        .agg(refund_count=("id", "count"), refund_amount=("_effective_refund", "sum"))
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
    df = df[_is_collected_charge(df["status"])]
    if df.empty:
        return pd.DataFrame(columns=cols)

    # Must have subscription_id
    if "subscription_id" not in df.columns:
        return pd.DataFrame(columns=cols)

    df = df[df["subscription_id"].notna() & (df["subscription_id"] != "") & (df["subscription_id"] != "nan")]
    if df.empty:
        return pd.DataFrame(columns=cols)

    df = enrich_charges_with_product(df, orders_df, subscriptions_df)
    df["net_amount"] = _net_charge_amount(df)
    df["created_at"] = _to_eastern(df["created_at"])
    df = df.dropna(subset=["created_at"])
    df["date"] = df["created_at"].dt.date

    # Keep only renewals (rank > 1, or rank 1 on old subscription)
    is_renewal = _identify_renewals(df, subscriptions_df)
    df = df[is_renewal]

    if df.empty:
        return pd.DataFrame(columns=cols)

    result = (
        df.groupby(["date", "product_id", "product_name"])
        .agg(renewal_count=("net_amount", "count"), renewal_revenue=("net_amount", "sum"))
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
    start_date=None,
    end_date=None,
) -> pd.DataFrame:
    """
    LTV analysis grouped by each customer's entry product (first purchase).

    When start_date/end_date are provided, only customers whose first purchase
    falls within that range are included. Their LTV still reflects all-time spend.

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
    first_orders = odf.loc[first_order_idx, ["customer_email", "created_at", "product_id", "product_name"]]

    # Filter to customers whose entry date falls within the date range
    if start_date is not None:
        first_orders = first_orders[first_orders["created_at"].dt.date >= start_date]
    if end_date is not None:
        first_orders = first_orders[first_orders["created_at"].dt.date <= end_date]

    first_orders = first_orders.drop(columns=["created_at"])
    first_orders = first_orders.rename(columns={
        "product_id": "entry_product_id",
        "product_name": "entry_product_name",
    })

    # Total spend per customer from collected charges (net of partial refunds)
    if not charges_df.empty:
        valid = charges_df[_is_collected_charge(charges_df["status"])].copy()
        if not valid.empty:
            valid["net_amount"] = _net_charge_amount(valid)
            spend = (
                valid.groupby("customer_email")["net_amount"]
                .sum()
                .reset_index()
                .rename(columns={"net_amount": "total_spend"})
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


# ------------------------------------------------------------------
# Shared helpers for new reports
# ------------------------------------------------------------------

_INTERVAL_MONTHLY_FACTOR = {
    "monthly": 1.0,
    "yearly": 1 / 12,
    "annual": 1 / 12,
    "weekly": 52 / 12,
    "biweekly": 26 / 12,
    "quarterly": 1 / 3,
    "semi-annual": 1 / 6,
    "daily": 365.25 / 12,
}

_INTERVAL_TO_OFFSET = {
    "monthly": pd.DateOffset(months=1),
    "yearly": pd.DateOffset(years=1),
    "annual": pd.DateOffset(years=1),
    "weekly": pd.DateOffset(weeks=1),
    "biweekly": pd.DateOffset(weeks=2),
    "quarterly": pd.DateOffset(months=3),
    "semi-annual": pd.DateOffset(months=6),
    "daily": pd.DateOffset(days=1),
}


def _normalize_to_monthly(price: float, interval: str) -> float:
    """Convert a subscription price to its monthly equivalent."""
    return price * _INTERVAL_MONTHLY_FACTOR.get(interval.lower().strip(), 1.0)


# ------------------------------------------------------------------
# Report 1: MRR Waterfall
# ------------------------------------------------------------------


def mrr_waterfall(subscriptions_df: pd.DataFrame) -> pd.DataFrame:
    """
    Monthly MRR waterfall: new, churned, reactivation, net MRR.

    Returns: month, new_mrr, churned_mrr, reactivation_mrr, net_mrr
    """
    cols = ["month", "new_mrr", "churned_mrr", "reactivation_mrr", "net_mrr"]
    if subscriptions_df.empty:
        return pd.DataFrame(columns=cols)

    subs = subscriptions_df.copy()
    subs["created_at"] = pd.to_datetime(subs["created_at"], errors="coerce", utc=True)
    subs["canceled_at"] = pd.to_datetime(subs["canceled_at"], errors="coerce", utc=True)
    subs = subs.dropna(subset=["created_at"])
    if subs.empty:
        return pd.DataFrame(columns=cols)

    subs["interval"] = subs["interval"].fillna("monthly")
    subs["price"] = subs["price"].fillna(0)
    subs["monthly_price"] = subs.apply(
        lambda r: _normalize_to_monthly(r["price"], r["interval"]), axis=1
    )
    subs["created_month"] = subs["created_at"].dt.to_period("M")
    subs["canceled_month"] = subs["canceled_at"].dt.to_period("M")

    # Build history of canceled subs per (customer_email, product_id)
    canceled_subs = subs[subs["canceled_at"].notna()].copy()

    all_months = sorted(subs["created_month"].dropna().unique())
    if subs["canceled_at"].notna().any():
        cancel_months = sorted(subs["canceled_month"].dropna().unique())
        all_months = sorted(set(all_months) | set(cancel_months))

    rows = []
    for month in all_months:
        new_mrr = 0.0
        reactivation_mrr = 0.0
        churned_mrr = 0.0

        # New / reactivation subs created this month
        created_this = subs[subs["created_month"] == month]
        for _, sub in created_this.iterrows():
            email = sub["customer_email"]
            pid = sub["product_id"]
            # Check for prior canceled sub for same customer+product
            prior_canceled = canceled_subs[
                (canceled_subs["customer_email"] == email)
                & (canceled_subs["product_id"] == pid)
                & (canceled_subs["canceled_at"] < sub["created_at"])
            ]
            if not prior_canceled.empty:
                # Check if there's an active sub at this point (concurrent)
                active_at_start = subs[
                    (subs["customer_email"] == email)
                    & (subs["product_id"] == pid)
                    & (subs["id"] != sub["id"])
                    & (subs["created_at"] < sub["created_at"])
                    & (subs["canceled_at"].isna() | (subs["canceled_at"] >= sub["created_at"]))
                ]
                if active_at_start.empty:
                    reactivation_mrr += sub["monthly_price"]
                else:
                    new_mrr += sub["monthly_price"]
            else:
                new_mrr += sub["monthly_price"]

        # Churned this month
        churned_this = subs[subs["canceled_month"] == month]
        churned_mrr = churned_this["monthly_price"].sum()

        rows.append({
            "month": str(month),
            "new_mrr": round(new_mrr, 2),
            "churned_mrr": round(churned_mrr, 2),
            "reactivation_mrr": round(reactivation_mrr, 2),
            "net_mrr": round(new_mrr + reactivation_mrr - churned_mrr, 2),
        })

    return pd.DataFrame(rows, columns=cols)


# ------------------------------------------------------------------
# Report 2: Revenue Forecast
# ------------------------------------------------------------------


def revenue_forecast(subscriptions_df: pd.DataFrame) -> pd.DataFrame:
    """
    Projected revenue from active subscriptions over 30/60/90 day windows.

    Returns: product_id, product_name, forecast_30d, forecast_60d, forecast_90d
    """
    cols = ["product_id", "product_name", "forecast_30d", "forecast_60d", "forecast_90d"]
    if subscriptions_df.empty:
        return pd.DataFrame(columns=cols)

    subs = subscriptions_df.copy()
    if "next_bill_date" not in subs.columns or subs["next_bill_date"].isna().all():
        return pd.DataFrame(columns=cols)
    if "interval" not in subs.columns or "price" not in subs.columns:
        return pd.DataFrame(columns=cols)

    subs = subs[subs["status"].str.lower() == "active"].copy()
    subs = subs[subs["next_bill_date"].notna()].copy()
    subs["interval"] = subs["interval"].fillna("monthly").str.lower().str.strip()
    subs = subs[subs["interval"].isin(_INTERVAL_TO_OFFSET)].copy()
    if subs.empty:
        return pd.DataFrame(columns=cols)

    subs["next_bill_date"] = pd.to_datetime(subs["next_bill_date"], errors="coerce", utc=True)
    subs = subs.dropna(subset=["next_bill_date"])
    if subs.empty:
        return pd.DataFrame(columns=cols)

    now = pd.Timestamp.now(tz="UTC")
    windows = {
        "forecast_30d": pd.Timedelta(days=30),
        "forecast_60d": pd.Timedelta(days=60),
        "forecast_90d": pd.Timedelta(days=90),
    }

    results = []
    for _, sub in subs.iterrows():
        offset = _INTERVAL_TO_OFFSET[sub["interval"]]
        price = sub["price"] if pd.notna(sub["price"]) else 0
        pid = sub["product_id"]
        pname = sub["product_name"]

        bill_date = sub["next_bill_date"]
        forecasts = {w: 0.0 for w in windows}
        # Project up to 90 days max
        max_end = now + pd.Timedelta(days=90)
        while bill_date <= max_end:
            delta = bill_date - now
            if delta >= pd.Timedelta(0):
                for w, window in windows.items():
                    if delta <= window:
                        forecasts[w] += price
            bill_date = bill_date + offset

        results.append({
            "product_id": pid,
            "product_name": pname,
            **forecasts,
        })

    if not results:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(results)
    return (
        df.groupby(["product_id", "product_name"])
        .agg(forecast_30d=("forecast_30d", "sum"), forecast_60d=("forecast_60d", "sum"), forecast_90d=("forecast_90d", "sum"))
        .reset_index()
        .sort_values("forecast_90d", ascending=False)
        .reset_index(drop=True)
    )


# ------------------------------------------------------------------
# Report 3: Refund Analysis
# ------------------------------------------------------------------


def refund_analysis(
    charges_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    subscriptions_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Refund analysis: by_product rates, time_to_refund, monthly_trend.

    Uses gross semantics (original charge amounts, not net).
    Returns (by_product, time_to_refund, monthly_trend).
    """
    empty_product = pd.DataFrame(columns=[
        "product_id", "product_name", "gross_charge_count", "refund_count",
        "gross_revenue", "refund_amount", "refund_rate_count_pct", "refund_rate_revenue_pct",
    ])
    empty_ttf = pd.DataFrame(columns=["product_id", "product_name", "days_to_refund"])
    empty_trend = pd.DataFrame(columns=["month", "refund_count", "refund_amount"])

    if charges_df.empty:
        return empty_product, empty_ttf, empty_trend

    df = charges_df.copy()
    df = enrich_charges_with_product(df, orders_df, subscriptions_df)

    # by_product: gross semantics
    gross = df[_is_gross_charge(df["status"])].copy()
    if gross.empty:
        return empty_product, empty_ttf, empty_trend

    refunds = df[_is_refund_charge(df["status"])].copy()

    # Aggregate by product
    gross_agg = (
        gross.groupby(["product_id", "product_name"])
        .agg(gross_charge_count=("id", "count"), gross_revenue=("amount", "sum"))
        .reset_index()
    )

    if not refunds.empty:
        refunds["_effective_refund"] = _refund_charge_amount(refunds)
        refund_agg = (
            refunds.groupby(["product_id", "product_name"])
            .agg(
                refund_count=("id", "count"),
                refund_amount=("_effective_refund", "sum"),
            )
            .reset_index()
        )
        by_product = gross_agg.merge(refund_agg, on=["product_id", "product_name"], how="left")
    else:
        by_product = gross_agg.copy()
        by_product["refund_count"] = 0
        by_product["refund_amount"] = 0.0

    by_product["refund_count"] = by_product["refund_count"].fillna(0).astype(int)
    by_product["refund_amount"] = by_product["refund_amount"].fillna(0.0)
    by_product["refund_rate_count_pct"] = (
        by_product["refund_count"] / by_product["gross_charge_count"] * 100
    ).round(2)
    by_product["refund_rate_revenue_pct"] = (
        by_product["refund_amount"] / by_product["gross_revenue"].replace(0, pd.NA) * 100
    ).fillna(0).round(2)
    by_product = by_product.sort_values("refund_rate_count_pct", ascending=False).reset_index(drop=True)

    # time_to_refund
    if not refunds.empty and "refund_date" in refunds.columns:
        ttf = refunds[refunds["refund_date"].notna()].copy()
        if not ttf.empty:
            ttf["created_at"] = pd.to_datetime(ttf["created_at"], errors="coerce", utc=True)
            ttf["refund_date"] = pd.to_datetime(ttf["refund_date"], errors="coerce", utc=True)
            ttf = ttf.dropna(subset=["created_at", "refund_date"])
            if not ttf.empty:
                ttf["days_to_refund"] = (ttf["refund_date"] - ttf["created_at"]).dt.days
                ttf = ttf[ttf["days_to_refund"] >= 0]
                time_to_refund = ttf[["product_id", "product_name", "days_to_refund"]].reset_index(drop=True)
            else:
                time_to_refund = empty_ttf
        else:
            time_to_refund = empty_ttf
    else:
        time_to_refund = empty_ttf

    # monthly_trend: group by refund_date month
    if not refunds.empty and "refund_date" in refunds.columns:
        trend = refunds[refunds["refund_date"].notna()].copy()
        if not trend.empty:
            trend["refund_date"] = pd.to_datetime(trend["refund_date"], errors="coerce", utc=True)
            trend = trend.dropna(subset=["refund_date"])
            if not trend.empty:
                if "_effective_refund" not in trend.columns:
                    trend["_effective_refund"] = _refund_charge_amount(trend)
                trend["month"] = trend["refund_date"].dt.to_period("M").astype(str)
                monthly_trend = (
                    trend.groupby("month")
                    .agg(refund_count=("id", "count"), refund_amount=("_effective_refund", "sum"))
                    .reset_index()
                    .sort_values("month")
                    .reset_index(drop=True)
                )
            else:
                monthly_trend = empty_trend
        else:
            monthly_trend = empty_trend
    else:
        monthly_trend = empty_trend

    return by_product, time_to_refund, monthly_trend


# ------------------------------------------------------------------
# Report 4: Churn Analysis
# ------------------------------------------------------------------


def churn_analysis(
    subscriptions_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Churn analysis: by_product rates and monthly trend.

    Returns (by_product, monthly_trend).
    """
    empty_product = pd.DataFrame(columns=[
        "product_id", "product_name", "total", "active", "canceled",
        "churn_rate", "avg_lifetime_days",
    ])
    empty_trend = pd.DataFrame(columns=["month", "created", "canceled", "cumulative_active"])

    if subscriptions_df.empty:
        return empty_product, empty_trend

    subs = subscriptions_df.copy()
    subs["status_lower"] = subs["status"].fillna("").str.lower()

    # by_product
    product_stats = []
    for (pid, pname), grp in subs.groupby(["product_id", "product_name"]):
        total = len(grp)
        active = (grp["status_lower"] == "active").sum()
        canceled = grp["status_lower"].isin(["canceled", "cancelled"]).sum()
        churn_rate = canceled / total * 100 if total > 0 else 0

        canceled_subs = grp[grp["canceled_at"].notna() & grp["status_lower"].isin(["canceled", "cancelled"])].copy()
        if not canceled_subs.empty:
            canceled_subs["created_at"] = pd.to_datetime(canceled_subs["created_at"], errors="coerce", utc=True)
            canceled_subs["canceled_at"] = pd.to_datetime(canceled_subs["canceled_at"], errors="coerce", utc=True)
            canceled_subs = canceled_subs.dropna(subset=["created_at", "canceled_at"])
            if not canceled_subs.empty:
                avg_life = (canceled_subs["canceled_at"] - canceled_subs["created_at"]).dt.days.mean()
            else:
                avg_life = 0
        else:
            avg_life = 0

        product_stats.append({
            "product_id": pid, "product_name": pname, "total": total,
            "active": active, "canceled": canceled,
            "churn_rate": round(churn_rate, 2), "avg_lifetime_days": round(avg_life, 1),
        })

    by_product = pd.DataFrame(product_stats)
    if by_product.empty:
        by_product = empty_product

    # monthly_trend
    subs["created_at"] = pd.to_datetime(subs["created_at"], errors="coerce", utc=True)
    subs["canceled_at"] = pd.to_datetime(subs["canceled_at"], errors="coerce", utc=True)
    subs = subs.dropna(subset=["created_at"])

    if subs.empty:
        return by_product, empty_trend

    subs["created_month"] = subs["created_at"].dt.to_period("M")
    created_by_month = subs.groupby("created_month").size().rename("created")

    canceled_subs = subs[subs["canceled_at"].notna()]
    if not canceled_subs.empty:
        canceled_subs = canceled_subs.copy()
        canceled_subs["canceled_month"] = canceled_subs["canceled_at"].dt.to_period("M")
        canceled_by_month = canceled_subs.groupby("canceled_month").size().rename("canceled")
    else:
        canceled_by_month = pd.Series(dtype=int, name="canceled")

    all_months = sorted(set(created_by_month.index) | set(canceled_by_month.index))
    trend_rows = []
    cumulative = 0
    for month in all_months:
        c = created_by_month.get(month, 0)
        x = canceled_by_month.get(month, 0)
        cumulative += c - x
        trend_rows.append({
            "month": str(month), "created": int(c),
            "canceled": int(x), "cumulative_active": max(cumulative, 0),
        })

    monthly_trend = pd.DataFrame(trend_rows) if trend_rows else empty_trend
    return by_product, monthly_trend


# ------------------------------------------------------------------
# Report 5: Trial-to-Paid Conversion
# ------------------------------------------------------------------


def trial_conversion(subscriptions_df: pd.DataFrame) -> pd.DataFrame:
    """
    Trial-to-paid conversion rates by product.

    Returns: product_id, product_name, trial_count, converted, dropped, conversion_rate_pct
    """
    cols = ["product_id", "product_name", "trial_count", "converted", "dropped", "conversion_rate_pct"]
    if subscriptions_df.empty:
        return pd.DataFrame(columns=cols)

    subs = subscriptions_df.copy()
    if "trial_days" not in subs.columns or subs["trial_days"].isna().all():
        return pd.DataFrame(columns=cols)

    subs["trial_days"] = pd.to_numeric(subs["trial_days"], errors="coerce").fillna(0)
    trials = subs[subs["trial_days"] > 0].copy()
    if trials.empty:
        return pd.DataFrame(columns=cols)

    trials["billing_cycle_count"] = pd.to_numeric(
        trials.get("billing_cycle_count", pd.Series(dtype=float)), errors="coerce"
    ).fillna(0)
    trials["status_lower"] = trials["status"].fillna("").str.lower()

    # Converted: billing_cycle_count >= 1
    trials["converted"] = trials["billing_cycle_count"] >= 1
    # Dropped: canceled AND 0 cycles
    trials["dropped"] = (
        trials["status_lower"].isin(["canceled", "cancelled"])
        & (trials["billing_cycle_count"] == 0)
    )
    # Still in trial (active + 0 cycles) excluded from denominator
    trials["resolved"] = trials["converted"] | trials["dropped"]

    resolved = trials[trials["resolved"]]
    if resolved.empty:
        return pd.DataFrame(columns=cols)

    result = (
        resolved.groupby(["product_id", "product_name"])
        .agg(
            trial_count=("id", "count"),
            converted=("converted", "sum"),
            dropped=("dropped", "sum"),
        )
        .reset_index()
    )
    result["conversion_rate_pct"] = (
        result["converted"] / result["trial_count"] * 100
    ).round(2)
    result["converted"] = result["converted"].astype(int)
    result["dropped"] = result["dropped"].astype(int)

    return result.sort_values("conversion_rate_pct", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------
# Report 6: Subscription Aging
# ------------------------------------------------------------------


def subscription_aging(subscriptions_df: pd.DataFrame) -> pd.DataFrame:
    """
    Age distribution of active subscriptions by product.

    Returns: product_id, product_name, age_bucket, count
    """
    cols = ["product_id", "product_name", "age_bucket", "count"]
    if subscriptions_df.empty:
        return pd.DataFrame(columns=cols)

    subs = subscriptions_df.copy()
    subs = subs[subs["status"].fillna("").str.lower() == "active"].copy()
    if subs.empty:
        return pd.DataFrame(columns=cols)

    subs["created_at"] = pd.to_datetime(subs["created_at"], errors="coerce", utc=True)
    subs = subs.dropna(subset=["created_at"])
    if subs.empty:
        return pd.DataFrame(columns=cols)

    now = pd.Timestamp.now(tz="UTC")
    subs["age_days"] = (now - subs["created_at"]).dt.days

    bins = [-1, 30, 90, 180, 365, 730, float("inf")]
    labels = ["0-30d", "31-90d", "91-180d", "181-365d", "1-2yr", "2yr+"]
    subs["age_bucket"] = pd.cut(subs["age_days"], bins=bins, labels=labels, right=True)

    result = (
        subs.groupby(["product_id", "product_name", "age_bucket"], observed=False)
        .size()
        .reset_index(name="count")
    )
    return result


# ------------------------------------------------------------------
# Report 7: RFM Segmentation
# ------------------------------------------------------------------


def rfm_segmentation(
    orders_df: pd.DataFrame,
    charges_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    RFM segmentation: Recency, Frequency, Monetary scoring.

    Returns: customer_email, recency_days, frequency, monetary,
             r_score, f_score, m_score, segment
    """
    cols = [
        "customer_email", "recency_days", "frequency", "monetary",
        "r_score", "f_score", "m_score", "segment",
    ]
    if charges_df.empty and orders_df.empty:
        return pd.DataFrame(columns=cols)

    # Recency: days since last collected charge
    now = pd.Timestamp.now(tz="UTC")
    if not charges_df.empty:
        collected = charges_df[_is_collected_charge(charges_df["status"])].copy()
        if not collected.empty:
            collected["created_at"] = pd.to_datetime(collected["created_at"], errors="coerce", utc=True)
            collected = collected.dropna(subset=["created_at"])
            recency = (
                collected.groupby("customer_email")["created_at"]
                .max()
                .reset_index()
            )
            recency["recency_days"] = (now - recency["created_at"]).dt.days
            recency = recency[["customer_email", "recency_days"]]
        else:
            recency = pd.DataFrame(columns=["customer_email", "recency_days"])
    else:
        recency = pd.DataFrame(columns=["customer_email", "recency_days"])

    # Frequency: distinct order count
    if not orders_df.empty:
        frequency = (
            orders_df.groupby("customer_email")["id"]
            .nunique()
            .reset_index()
            .rename(columns={"id": "frequency"})
        )
    else:
        frequency = pd.DataFrame(columns=["customer_email", "frequency"])

    # Monetary: total net charge amount
    if not charges_df.empty:
        collected = charges_df[_is_collected_charge(charges_df["status"])].copy()
        if not collected.empty:
            collected["net_amount"] = _net_charge_amount(collected)
            monetary = (
                collected.groupby("customer_email")["net_amount"]
                .sum()
                .reset_index()
                .rename(columns={"net_amount": "monetary"})
            )
        else:
            monetary = pd.DataFrame(columns=["customer_email", "monetary"])
    else:
        monetary = pd.DataFrame(columns=["customer_email", "monetary"])

    # Merge
    if recency.empty and frequency.empty:
        return pd.DataFrame(columns=cols)

    rfm = recency
    if not frequency.empty:
        rfm = rfm.merge(frequency, on="customer_email", how="outer") if not rfm.empty else frequency
    if not monetary.empty:
        rfm = rfm.merge(monetary, on="customer_email", how="outer") if not rfm.empty else monetary

    rfm["recency_days"] = rfm.get("recency_days", pd.Series(dtype=float)).fillna(9999)
    rfm["frequency"] = rfm.get("frequency", pd.Series(dtype=float)).fillna(0).astype(int)
    rfm["monetary"] = rfm.get("monetary", pd.Series(dtype=float)).fillna(0.0)

    # Need at least 10 customers for meaningful quintiles
    if len(rfm) < 10:
        return pd.DataFrame(columns=cols)

    # Score with quintiles (R inverted — lower recency = higher score)
    try:
        rfm["r_score"] = pd.qcut(rfm["recency_days"], q=5, labels=[5, 4, 3, 2, 1], duplicates="drop").astype(int)
    except ValueError:
        rfm["r_score"] = 3
    try:
        rfm["f_score"] = pd.qcut(rfm["frequency"], q=5, labels=[1, 2, 3, 4, 5], duplicates="drop").astype(int)
    except ValueError:
        rfm["f_score"] = 3
    try:
        rfm["m_score"] = pd.qcut(rfm["monetary"], q=5, labels=[1, 2, 3, 4, 5], duplicates="drop").astype(int)
    except ValueError:
        rfm["m_score"] = 3

    # Segment assignment
    def _segment(row):
        r, f = row["r_score"], row["f_score"]
        if r >= 4 and f >= 4:
            return "Champions"
        if r >= 3 and f >= 3:
            return "Loyal"
        if r >= 4 and f <= 2:
            return "New"
        if r >= 3 and f <= 2:
            return "Potential Loyalists"
        if r <= 2 and f >= 3:
            return "At Risk"
        if r <= 2 and f <= 2:
            return "Lost"
        return "Hibernating"

    rfm["segment"] = rfm.apply(_segment, axis=1)
    return rfm[cols].sort_values("monetary", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------
# Report 8: Multi-Product Buyers
# ------------------------------------------------------------------


def multi_product_buyers(
    orders_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Multi-product buyer analysis (primary order product only).

    Returns (buyer_summary, product_combos).
    """
    import itertools

    empty_buyers = pd.DataFrame(columns=["customer_email", "product_count", "products"])
    empty_combos = pd.DataFrame(columns=["product_a", "product_b", "pair_count"])

    if orders_df.empty:
        return empty_buyers, empty_combos

    df = orders_df.copy()
    # Distinct products per customer
    customer_products = (
        df.groupby("customer_email")["product_id"]
        .apply(lambda x: list(x.unique()))
        .reset_index()
    )
    customer_products["product_count"] = customer_products["product_id"].apply(len)
    multi = customer_products[customer_products["product_count"] >= 2].copy()

    if multi.empty:
        return empty_buyers, empty_combos

    # Product name map
    name_map = df.drop_duplicates("product_id", keep="last").set_index("product_id")["product_name"].to_dict()

    # Buyer summary
    multi["products"] = multi["product_id"].apply(
        lambda pids: ", ".join(name_map.get(p, p) for p in sorted(pids))
    )
    buyer_summary = multi[["customer_email", "product_count", "products"]].sort_values(
        "product_count", ascending=False
    ).reset_index(drop=True)

    # Product combos
    combo_counts: dict[tuple, int] = {}
    for pids in multi["product_id"]:
        for pair in itertools.combinations(sorted(pids), 2):
            combo_counts[pair] = combo_counts.get(pair, 0) + 1

    if combo_counts:
        combo_rows = [
            {"product_a": name_map.get(a, a), "product_b": name_map.get(b, b), "pair_count": c}
            for (a, b), c in combo_counts.items()
        ]
        product_combos = (
            pd.DataFrame(combo_rows)
            .sort_values("pair_count", ascending=False)
            .reset_index(drop=True)
        )
    else:
        product_combos = empty_combos

    return buyer_summary, product_combos


# ------------------------------------------------------------------
# Report 9: Customer Concentration (Pareto)
# ------------------------------------------------------------------


def customer_concentration(charges_df: pd.DataFrame) -> pd.DataFrame:
    """
    Revenue concentration: ranked customers with cumulative % (Pareto).

    Returns: rank, customer_email, total_revenue, cumulative_revenue, cumulative_pct
    """
    cols = ["rank", "customer_email", "total_revenue", "cumulative_revenue", "cumulative_pct"]
    if charges_df.empty:
        return pd.DataFrame(columns=cols)

    collected = charges_df[_is_collected_charge(charges_df["status"])].copy()
    if collected.empty:
        return pd.DataFrame(columns=cols)

    collected["net_amount"] = _net_charge_amount(collected)
    revenue = (
        collected.groupby("customer_email")["net_amount"]
        .sum()
        .reset_index()
        .rename(columns={"net_amount": "total_revenue"})
        .sort_values("total_revenue", ascending=False)
        .reset_index(drop=True)
    )

    revenue["rank"] = range(1, len(revenue) + 1)
    revenue["cumulative_revenue"] = revenue["total_revenue"].cumsum()
    total = revenue["total_revenue"].sum()
    revenue["cumulative_pct"] = (revenue["cumulative_revenue"] / total * 100).round(2) if total > 0 else 0

    return revenue[cols]


# ------------------------------------------------------------------
# Report 10: Product MRR Trend
# ------------------------------------------------------------------


def product_mrr_trend(subscriptions_df: pd.DataFrame) -> pd.DataFrame:
    """
    Monthly MRR per product over time.

    Returns: month, product_id, product_name, mrr
    """
    cols = ["month", "product_id", "product_name", "mrr"]
    if subscriptions_df.empty:
        return pd.DataFrame(columns=cols)

    subs = subscriptions_df.copy()
    subs["created_at"] = pd.to_datetime(subs["created_at"], errors="coerce", utc=True)
    subs["canceled_at"] = pd.to_datetime(subs["canceled_at"], errors="coerce", utc=True)
    subs = subs.dropna(subset=["created_at"])
    if subs.empty:
        return pd.DataFrame(columns=cols)

    subs["interval"] = subs["interval"].fillna("monthly")
    subs["price"] = subs["price"].fillna(0)
    subs["monthly_price"] = subs.apply(
        lambda r: _normalize_to_monthly(r["price"], r["interval"]), axis=1
    )

    now_period = pd.Timestamp.now(tz="UTC").to_period("M")
    rows = []
    for _, sub in subs.iterrows():
        start = sub["created_at"].to_period("M")
        if pd.notna(sub["canceled_at"]):
            end = sub["canceled_at"].to_period("M")
        else:
            end = now_period

        if start > end:
            continue

        periods = pd.period_range(start, end, freq="M")
        for p in periods:
            rows.append({
                "month": str(p),
                "product_id": sub["product_id"],
                "product_name": sub["product_name"],
                "mrr": sub["monthly_price"],
            })

    if not rows:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows)
    result = (
        df.groupby(["month", "product_id", "product_name"])
        .agg(mrr=("mrr", "sum"))
        .reset_index()
        .sort_values("month")
        .reset_index(drop=True)
    )
    return result


# ------------------------------------------------------------------
# Report 11: Product Attach Rate
# ------------------------------------------------------------------


def product_attach_rate(orders_df: pd.DataFrame) -> pd.DataFrame:
    """
    Cross-sell attach rate: for each product pair, what % of product_a buyers also bought product_b.

    Primary order product only. Min 5 buyers per product.
    Returns: product_a, product_b, buyers_of_a, bought_both, attach_rate_pct
    """
    cols = ["product_a", "product_b", "buyers_of_a", "bought_both", "attach_rate_pct"]
    if orders_df.empty:
        return pd.DataFrame(columns=cols)

    df = orders_df.copy()
    # Products per customer
    customer_products = df.groupby("customer_email")["product_id"].apply(set).to_dict()
    # Product name map
    name_map = df.drop_duplicates("product_id", keep="last").set_index("product_id")["product_name"].to_dict()

    # Count buyers per product
    product_buyers: dict[str, set] = {}
    for email, pids in customer_products.items():
        for pid in pids:
            product_buyers.setdefault(pid, set()).add(email)

    # Filter to min 5 buyers
    valid_products = {pid for pid, buyers in product_buyers.items() if len(buyers) >= 5}
    if len(valid_products) < 2:
        return pd.DataFrame(columns=cols)

    rows = []
    for pid_a in sorted(valid_products):
        for pid_b in sorted(valid_products):
            if pid_a == pid_b:
                continue
            buyers_a = product_buyers[pid_a]
            both = buyers_a & product_buyers[pid_b]
            rows.append({
                "product_a": name_map.get(pid_a, pid_a),
                "product_b": name_map.get(pid_b, pid_b),
                "buyers_of_a": len(buyers_a),
                "bought_both": len(both),
                "attach_rate_pct": round(len(both) / len(buyers_a) * 100, 2),
            })

    return pd.DataFrame(rows, columns=cols).sort_values("attach_rate_pct", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------
# Report 12: New vs Renewal Revenue Mix
# ------------------------------------------------------------------


def new_vs_renewal_revenue_mix(
    charges_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    subscriptions_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Monthly revenue split: new (initial) vs renewal by product.

    Returns: product_id, product_name, month, new_revenue, renewal_revenue,
             total_revenue, new_pct, renewal_pct
    """
    cols = [
        "product_id", "product_name", "month", "new_revenue", "renewal_revenue",
        "total_revenue", "new_pct", "renewal_pct",
    ]
    if charges_df.empty:
        return pd.DataFrame(columns=cols)

    df = charges_df.copy()
    df = df[_is_collected_charge(df["status"])].copy()
    if df.empty:
        return pd.DataFrame(columns=cols)

    df = enrich_charges_with_product(df, orders_df, subscriptions_df)
    df["net_amount"] = _net_charge_amount(df)
    df["created_at"] = _to_eastern(df["created_at"])
    df = df.dropna(subset=["created_at"])
    df["month"] = df["created_at"].dt.to_period("M").astype(str)

    is_renewal = _identify_renewals(df, subscriptions_df)
    df["is_renewal"] = is_renewal

    new_rev = (
        df[~df["is_renewal"]]
        .groupby(["product_id", "product_name", "month"])
        .agg(new_revenue=("net_amount", "sum"))
        .reset_index()
    )
    ren_rev = (
        df[df["is_renewal"]]
        .groupby(["product_id", "product_name", "month"])
        .agg(renewal_revenue=("net_amount", "sum"))
        .reset_index()
    )

    result = new_rev.merge(ren_rev, on=["product_id", "product_name", "month"], how="outer")
    result["new_revenue"] = result["new_revenue"].fillna(0)
    result["renewal_revenue"] = result["renewal_revenue"].fillna(0)
    result["total_revenue"] = result["new_revenue"] + result["renewal_revenue"]
    result["new_pct"] = (
        result["new_revenue"] / result["total_revenue"].replace(0, pd.NA) * 100
    ).fillna(0).round(2)
    result["renewal_pct"] = (
        result["renewal_revenue"] / result["total_revenue"].replace(0, pd.NA) * 100
    ).fillna(0).round(2)

    return result.sort_values(["product_name", "month"]).reset_index(drop=True)
