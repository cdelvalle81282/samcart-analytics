"""Report catalog — maps report type keys to generator functions.

Each generator follows the signature:
    generate_<type>(cache, date_range_days=30, product_filter=None, **kwargs) -> pd.DataFrame
"""

from __future__ import annotations

from datetime import datetime as _datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from cache import SamCartCache

# The analytics layer (build_daily_summary, to_eastern, page filters) always
# buckets dates in Eastern time.  Scheduled reports must use the same timezone
# for date-window computation so their output matches the UI, regardless of
# which timezone the user chose for delivery scheduling.
_ANALYTICS_TZ = ZoneInfo("America/New_York")


def _load_data(cache: SamCartCache) -> dict:
    """Load all data from cache into a dict of DataFrames."""
    return {
        "orders": cache.get_orders_df(),
        "charges": cache.get_charges_df(),
        "subscriptions": cache.get_subscriptions_df(),
        "products": cache.get_products_df(),
    }


def _filter_by_date(df: pd.DataFrame, col: str, days: int) -> pd.DataFrame:
    """Filter a DataFrame to rows on or after (today - N Eastern calendar days).

    Anchored to Eastern time to match the analytics layer and page filters.
    Records near local midnight are bucketed by their Eastern calendar date,
    not UTC, matching the inclusive date picker on every report page.
    """
    if df.empty or col not in df.columns:
        return df
    df = df.copy()
    df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
    cutoff_date = _datetime.now(tz=_ANALYTICS_TZ).date() - timedelta(days=days)
    local_dates = df[col].dt.tz_convert(_ANALYTICS_TZ).dt.date
    return df[local_dates >= cutoff_date]


# ------------------------------------------------------------------
# Existing generators (with bug fixes and **kwargs added)
# ------------------------------------------------------------------


def generate_daily_metrics(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    return _daily_metrics_base(cache, date_range_days, product_filter)


def _daily_metrics_base(
    cache: SamCartCache, date_range_days: int, product_filter: list[str] | None,
) -> pd.DataFrame:
    """Shared helper: full-history summary trimmed to date window.

    build_daily_summary already buckets rows into Eastern calendar dates and
    stores them as naive midnight timestamps.  Parse without utc=True and
    compare .dt.date directly — both anchored to Eastern — matching the page.
    """
    from analytics import build_daily_summary
    data = _load_data(cache)
    df = build_daily_summary(data["orders"], data["charges"], data["subscriptions"])
    if not df.empty and "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        cutoff_date = _datetime.now(tz=_ANALYTICS_TZ).date() - timedelta(days=date_range_days)
        df = df[df["date"].dt.date >= cutoff_date]
    if product_filter and "product_name" in df.columns:
        df = df[df["product_name"].isin(product_filter)]
    return df


def generate_daily_metrics_new_customers(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    df = _daily_metrics_base(cache, date_range_days, product_filter)
    cols = [c for c in ["date", "product_name", "new_customer_count"] if c in df.columns]
    return (
        df[cols].groupby(["date", "product_name"], as_index=False)["new_customer_count"].sum()
        if not df.empty else df[cols]
    )


def generate_daily_metrics_new_sales(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    df = _daily_metrics_base(cache, date_range_days, product_filter)
    cols = [c for c in ["date", "product_name", "sale_count", "sale_revenue"] if c in df.columns]
    if df.empty:
        return df[cols]
    return df[cols].groupby(["date", "product_name"], as_index=False).agg(
        sale_count=("sale_count", "sum"), sale_revenue=("sale_revenue", "sum")
    )


def generate_daily_metrics_refunds(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    df = _daily_metrics_base(cache, date_range_days, product_filter)
    cols = [c for c in ["date", "product_name", "refund_count", "refund_amount"] if c in df.columns]
    if df.empty:
        return df[cols]
    return df[cols].groupby(["date", "product_name"], as_index=False).agg(
        refund_count=("refund_count", "sum"), refund_amount=("refund_amount", "sum")
    )


def generate_daily_metrics_renewals(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    df = _daily_metrics_base(cache, date_range_days, product_filter)
    cols = [c for c in ["date", "product_name", "renewal_count", "renewal_revenue"] if c in df.columns]
    if df.empty:
        return df[cols]
    return df[cols].groupby(["date", "product_name"], as_index=False).agg(
        renewal_count=("renewal_count", "sum"), renewal_revenue=("renewal_revenue", "sum")
    )


def generate_refund_analysis(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import refund_analysis
    data = _load_data(cache)
    result = refund_analysis(data["charges"], data["orders"], data["subscriptions"])
    df = result[0]  # by_product DataFrame
    if product_filter and not df.empty and "product_name" in df.columns:
        df = df[df["product_name"].isin(product_filter)]
    return df


def generate_product_ltv(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import product_ltv_ranking
    data = _load_data(cache)
    orders = _filter_by_date(data["orders"], "created_at", date_range_days)
    df = product_ltv_ranking(orders, data["subscriptions"], data["products"])
    if product_filter and not df.empty and "product_name" in df.columns:
        df = df[df["product_name"].isin(product_filter)]
    min_orders = int(kwargs.get("min_orders", 0))
    if min_orders > 0 and "order_count" in df.columns:
        df = df[df["order_count"] >= min_orders]
    return df


def generate_subscription_health(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import churn_analysis
    data = _load_data(cache)
    result = churn_analysis(data["subscriptions"])
    df = result[0]  # by_product DataFrame
    if product_filter and not df.empty and "product_name" in df.columns:
        df = df[df["product_name"].isin(product_filter)]
    return df


def generate_customer_segments(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import rfm_segmentation
    data = _load_data(cache)
    df = rfm_segmentation(data["orders"], data["charges"])
    segment_filter = kwargs.get("segment_filter")
    if segment_filter and segment_filter != "All" and "segment" in df.columns:
        df = df[df["segment"] == segment_filter]
    return df


def generate_product_deep_dive(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import product_mrr_trend
    data = _load_data(cache)
    df = product_mrr_trend(data["subscriptions"])
    if product_filter and not df.empty and "product_name" in df.columns:
        df = df[df["product_name"].isin(product_filter)]
    return df


def generate_revenue_forecast(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import revenue_forecast
    data = _load_data(cache)
    return revenue_forecast(data["subscriptions"])


def generate_mrr_waterfall(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import mrr_waterfall
    data = _load_data(cache)
    return mrr_waterfall(data["subscriptions"])


def generate_upcoming_renewals(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import upcoming_renewals_and_cancellations
    data = _load_data(cache)
    weeks = max(1, date_range_days // 7)
    result = upcoming_renewals_and_cancellations(
        data["subscriptions"], lookahead_weeks=weeks, product_filter=product_filter,
    )
    renewals = result["renewals"].copy()
    if not renewals.empty:
        renewals["type"] = "renewal"
    cancellations = result["cancellations"].copy()
    if not cancellations.empty:
        cancellations["type"] = "cancellation"
    return pd.concat([renewals, cancellations], ignore_index=True)


def generate_vip_customers(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
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
# New generators (14 additional tab/view-level entries)
# ------------------------------------------------------------------


def generate_daily_metrics_entry_ltv(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import new_customer_ltv_by_entry_product
    data = _load_data(cache)
    end = _datetime.now(tz=_ANALYTICS_TZ).date()
    start = end - timedelta(days=date_range_days)
    df = new_customer_ltv_by_entry_product(
        data["orders"], data["charges"], data["subscriptions"],
        start_date=start, end_date=end,
    )
    if product_filter and not df.empty and "product_name" in df.columns:
        df = df[df["product_name"].isin(product_filter)]
    return df


def generate_cohort_activity(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import build_cohort_performance
    data = _load_data(cache)
    product_id = kwargs.get("product_id") or None
    interval_filter = kwargs.get("interval_filter") or None
    result = build_cohort_performance(
        data["charges"], data["orders"], data["subscriptions"],
        product_filter=product_id, interval_filter=interval_filter,
    )
    return result[0]  # activity summary


def generate_cohort_renewal_rates(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import build_cohort_performance
    data = _load_data(cache)
    product_id = kwargs.get("product_id") or None
    interval_filter = kwargs.get("interval_filter") or None
    result = build_cohort_performance(
        data["charges"], data["orders"], data["subscriptions"],
        product_filter=product_id, interval_filter=interval_filter,
    )
    return result[1]  # renewal_rates


def generate_cohort_stick_rates(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import build_cohort_performance
    data = _load_data(cache)
    product_id = kwargs.get("product_id") or None
    interval_filter = kwargs.get("interval_filter") or None
    result = build_cohort_performance(
        data["charges"], data["orders"], data["subscriptions"],
        product_filter=product_id, interval_filter=interval_filter,
    )
    return result[2]  # stick_rates


def generate_cohort_heatmap(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import build_cohort_heatmap
    data = _load_data(cache)
    product_id = kwargs.get("product_id") or None
    interval_filter = kwargs.get("interval_filter") or None
    df = build_cohort_heatmap(
        data["charges"], data["orders"], data["subscriptions"],
        product_filter=product_id, interval_filter=interval_filter,
    )
    if not df.empty:
        df = df.reset_index()
    return df


def generate_refund_time_to_refund(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import refund_analysis
    data = _load_data(cache)
    result = refund_analysis(data["charges"], data["orders"], data["subscriptions"])
    df = result[1]  # time_to_refund
    if product_filter and not df.empty and "product_name" in df.columns:
        df = df[df["product_name"].isin(product_filter)]
    return df


def generate_refund_monthly_trend(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import refund_analysis
    data = _load_data(cache)
    result = refund_analysis(data["charges"], data["orders"], data["subscriptions"])
    return result[2]  # monthly_trend


def generate_subscription_health_churn_trend(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import churn_analysis
    data = _load_data(cache)
    result = churn_analysis(data["subscriptions"])
    return result[1]  # monthly_trend


def generate_subscription_health_trial(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import trial_conversion
    data = _load_data(cache)
    return trial_conversion(data["subscriptions"])


def generate_subscription_health_aging(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import subscription_aging
    data = _load_data(cache)
    return subscription_aging(data["subscriptions"])


def generate_customer_segments_multi_product(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import multi_product_buyers
    data = _load_data(cache)
    result = multi_product_buyers(data["orders"])
    return result[0]  # buyer_summary


def generate_customer_segments_concentration(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import customer_concentration
    data = _load_data(cache)
    return customer_concentration(data["charges"])


def generate_product_deep_dive_attach(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import product_attach_rate
    data = _load_data(cache)
    return product_attach_rate(data["orders"])


def generate_product_deep_dive_revenue_mix(
    cache: SamCartCache, date_range_days: int = 30, product_filter: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    from analytics import new_vs_renewal_revenue_mix
    data = _load_data(cache)
    df = new_vs_renewal_revenue_mix(data["charges"], data["orders"], data["subscriptions"])
    if product_filter and not df.empty and "product_name" in df.columns:
        df = df[df["product_name"].isin(product_filter)]
    return df


# ------------------------------------------------------------------
# Catalog registry
# ------------------------------------------------------------------

REPORT_CATALOG: dict[str, dict] = {
    # --- Daily Metrics ---
    "daily_metrics": {
        "name": "Daily Metrics — Daily Summary",
        "generator": generate_daily_metrics,
    },
    "daily_metrics_new_customers": {
        "name": "Daily Metrics — New Customers Trend",
        "generator": generate_daily_metrics_new_customers,
    },
    "daily_metrics_new_sales": {
        "name": "Daily Metrics — New Sales Trend",
        "generator": generate_daily_metrics_new_sales,
    },
    "daily_metrics_refunds": {
        "name": "Daily Metrics — Refunds Trend",
        "generator": generate_daily_metrics_refunds,
    },
    "daily_metrics_renewals": {
        "name": "Daily Metrics — Renewals Trend",
        "generator": generate_daily_metrics_renewals,
    },
    "daily_metrics_entry_ltv": {
        "name": "Daily Metrics — Entry Product LTV",
        "generator": generate_daily_metrics_entry_ltv,
    },
    # --- Subscription Cohorts ---
    "cohort_activity": {
        "name": "Subscription Cohorts — Activity Summary",
        "generator": generate_cohort_activity,
    },
    "cohort_renewal_rates": {
        "name": "Subscription Cohorts — Renewal Rates",
        "generator": generate_cohort_renewal_rates,
    },
    "cohort_stick_rates": {
        "name": "Subscription Cohorts — Stick & Refund Rates",
        "generator": generate_cohort_stick_rates,
    },
    "cohort_heatmap": {
        "name": "Subscription Cohorts — Retention Heatmap",
        "generator": generate_cohort_heatmap,
    },
    # --- Refund Analysis ---
    "refund_analysis": {
        "name": "Refund Analysis — By Product",
        "generator": generate_refund_analysis,
    },
    "refund_time_to_refund": {
        "name": "Refund Analysis — Time to Refund",
        "generator": generate_refund_time_to_refund,
    },
    "refund_monthly_trend": {
        "name": "Refund Analysis — Monthly Trend",
        "generator": generate_refund_monthly_trend,
    },
    # --- Product LTV ---
    "product_ltv": {
        "name": "Product LTV Compare",
        "generator": generate_product_ltv,
    },
    # --- Subscription Health ---
    "subscription_health": {
        "name": "Subscription Health — Churn by Product",
        "generator": generate_subscription_health,
    },
    "subscription_health_churn_trend": {
        "name": "Subscription Health — Churn Trend",
        "generator": generate_subscription_health_churn_trend,
    },
    "subscription_health_trial": {
        "name": "Subscription Health — Trial-to-Paid",
        "generator": generate_subscription_health_trial,
    },
    "subscription_health_aging": {
        "name": "Subscription Health — Subscription Aging",
        "generator": generate_subscription_health_aging,
    },
    # --- Customer Segments ---
    "customer_segments": {
        "name": "Customer Segments — RFM",
        "generator": generate_customer_segments,
    },
    "customer_segments_multi_product": {
        "name": "Customer Segments — Multi-Product Buyers",
        "generator": generate_customer_segments_multi_product,
    },
    "customer_segments_concentration": {
        "name": "Customer Segments — Revenue Concentration",
        "generator": generate_customer_segments_concentration,
    },
    # --- Product Deep Dive ---
    "product_deep_dive": {
        "name": "Product Deep Dive — MRR Trend",
        "generator": generate_product_deep_dive,
    },
    "product_deep_dive_attach": {
        "name": "Product Deep Dive — Attach Rate",
        "generator": generate_product_deep_dive_attach,
    },
    "product_deep_dive_revenue_mix": {
        "name": "Product Deep Dive — Revenue Mix",
        "generator": generate_product_deep_dive_revenue_mix,
    },
    # --- Revenue Forecasting ---
    "mrr_waterfall": {
        "name": "Revenue Forecasting — MRR Waterfall",
        "generator": generate_mrr_waterfall,
    },
    "revenue_forecast": {
        "name": "Revenue Forecasting — Revenue Forecast",
        "generator": generate_revenue_forecast,
    },
    # --- Other ---
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
    **kwargs,
) -> pd.DataFrame:
    """Generate a report by type key. Raises KeyError for unknown types."""
    entry = REPORT_CATALOG[report_type]
    return entry["generator"](cache, date_range_days=date_range_days, product_filter=product_filter, **kwargs)
