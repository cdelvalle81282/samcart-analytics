"""Report catalog — maps report type keys to generator functions.

Each generator follows the signature:
    generate_<type>(cache, date_range_days=30, product_filter=None) -> pd.DataFrame
"""

from __future__ import annotations

import pandas as pd

from cache import SamCartCache


def _load_data(cache: SamCartCache) -> dict:
    """Load all data from cache into a dict of DataFrames."""
    return {
        "orders": cache.get_orders_df(),
        "charges": cache.get_charges_df(),
        "subscriptions": cache.get_subscriptions_df(),
        "products": cache.get_products_df(),
    }


def _filter_by_date(df: pd.DataFrame, col: str, days: int) -> pd.DataFrame:
    """Filter a DataFrame to rows within the last N days."""
    if df.empty or col not in df.columns:
        return df
    df = df.copy()
    df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
    return df[df[col] >= cutoff]


# ------------------------------------------------------------------
# Individual generators
# ------------------------------------------------------------------


def generate_daily_metrics(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
) -> pd.DataFrame:
    from analytics import build_daily_summary
    data = _load_data(cache)
    orders = _filter_by_date(data["orders"], "created_at", date_range_days)
    charges = _filter_by_date(data["charges"], "created_at", date_range_days)
    subs = data["subscriptions"]
    df = build_daily_summary(orders, charges, subs)
    if product_filter and "product_name" in df.columns:
        df = df[df["product_name"].isin(product_filter)]
    return df


def generate_refund_analysis(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
) -> pd.DataFrame:
    from analytics import refund_analysis
    data = _load_data(cache)
    result = refund_analysis(data["charges"], data["orders"], data["subscriptions"])
    df = result.get("by_product", pd.DataFrame())
    if product_filter and not df.empty and "product_name" in df.columns:
        df = df[df["product_name"].isin(product_filter)]
    return df


def generate_cohort_performance(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
) -> pd.DataFrame:
    from analytics import build_cohort_performance
    data = _load_data(cache)
    return build_cohort_performance(
        data["charges"], data["orders"], data["subscriptions"],
        product_filter=product_filter,
    )


def generate_product_ltv(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
) -> pd.DataFrame:
    from analytics import product_ltv_ranking
    data = _load_data(cache)
    df = product_ltv_ranking(data["orders"], data["subscriptions"], data["products"])
    if product_filter and not df.empty and "product_name" in df.columns:
        df = df[df["product_name"].isin(product_filter)]
    return df


def generate_subscription_health(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
) -> pd.DataFrame:
    from analytics import churn_analysis
    data = _load_data(cache)
    result = churn_analysis(data["subscriptions"])
    df = result.get("by_product", pd.DataFrame())
    if product_filter and not df.empty and "product_name" in df.columns:
        df = df[df["product_name"].isin(product_filter)]
    return df


def generate_customer_segments(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
) -> pd.DataFrame:
    from analytics import rfm_segmentation
    data = _load_data(cache)
    return rfm_segmentation(data["charges"], data["orders"])


def generate_product_deep_dive(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
) -> pd.DataFrame:
    from analytics import product_mrr_trend
    data = _load_data(cache)
    df = product_mrr_trend(data["subscriptions"])
    if product_filter and not df.empty and "product_name" in df.columns:
        df = df[df["product_name"].isin(product_filter)]
    return df


def generate_revenue_forecast(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
) -> pd.DataFrame:
    from analytics import revenue_forecast
    data = _load_data(cache)
    return revenue_forecast(data["subscriptions"])


def generate_mrr_waterfall(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
) -> pd.DataFrame:
    from analytics import mrr_waterfall
    data = _load_data(cache)
    return mrr_waterfall(data["subscriptions"])


def generate_upcoming_renewals(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
) -> pd.DataFrame:
    from analytics import upcoming_renewals_and_cancellations
    data = _load_data(cache)
    # Map date_range_days to lookahead weeks (7 days = 1 week)
    weeks = max(1, date_range_days // 7)
    result = upcoming_renewals_and_cancellations(
        data["subscriptions"], lookahead_weeks=weeks, product_filter=product_filter,
    )
    # Combine renewals and cancellations into one DataFrame
    renewals = result["renewals"].copy()
    if not renewals.empty:
        renewals["type"] = "renewal"
    cancellations = result["cancellations"].copy()
    if not cancellations.empty:
        cancellations["type"] = "cancellation"
    return pd.concat([renewals, cancellations], ignore_index=True)


def generate_vip_customers(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
) -> pd.DataFrame:
    from analytics import vip_customers
    data = _load_data(cache)
    result = vip_customers(
        data["charges"], data["orders"], data["subscriptions"],
        product_filter=product_filter,
    )
    high_ltv = result["high_ltv"].copy()
    if not high_ltv.empty:
        high_ltv["vip_type"] = "high_ltv"
    loyal = result["loyal_subscribers"].copy()
    if not loyal.empty:
        loyal["vip_type"] = "loyal_subscriber"
    return pd.concat([high_ltv, loyal], ignore_index=True)


# ------------------------------------------------------------------
# Catalog registry
# ------------------------------------------------------------------

REPORT_CATALOG: dict[str, dict] = {
    "daily_metrics": {
        "name": "Daily Metrics",
        "generator": generate_daily_metrics,
    },
    "refund_analysis": {
        "name": "Refund Analysis",
        "generator": generate_refund_analysis,
    },
    "cohort_performance": {
        "name": "Cohort Performance",
        "generator": generate_cohort_performance,
    },
    "product_ltv": {
        "name": "Product LTV",
        "generator": generate_product_ltv,
    },
    "subscription_health": {
        "name": "Subscription Health",
        "generator": generate_subscription_health,
    },
    "customer_segments": {
        "name": "Customer Segments (RFM)",
        "generator": generate_customer_segments,
    },
    "product_deep_dive": {
        "name": "Product Deep Dive (MRR Trend)",
        "generator": generate_product_deep_dive,
    },
    "revenue_forecast": {
        "name": "Revenue Forecast",
        "generator": generate_revenue_forecast,
    },
    "mrr_waterfall": {
        "name": "MRR Waterfall",
        "generator": generate_mrr_waterfall,
    },
    "upcoming_renewals": {
        "name": "Upcoming Renewals & Cancellations",
        "generator": generate_upcoming_renewals,
    },
    "vip_customers": {
        "name": "VIP Customers",
        "generator": generate_vip_customers,
    },
}


def generate_report(
    report_type: str,
    cache: SamCartCache,
    date_range_days: int = 30,
    product_filter: list[str] | None = None,
) -> pd.DataFrame:
    """Generate a report by type key. Raises KeyError for unknown types."""
    entry = REPORT_CATALOG[report_type]
    return entry["generator"](cache, date_range_days=date_range_days, product_filter=product_filter)
