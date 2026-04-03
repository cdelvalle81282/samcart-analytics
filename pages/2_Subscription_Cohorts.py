"""Report 2: Charge-Based Cohort Performance Report."""

import pandas as pd
import plotly.express as px
import streamlit as st

from analytics import build_cohort_heatmap, build_cohort_performance
from auth import require_auth
from export import render_export_buttons
from methodology import COHORT_RETENTION_METHODOLOGY
from shared import load_charges, load_orders, load_products, load_subscriptions, render_doc_tabs, render_sync_sidebar

st.set_page_config(
    page_title="Subscription Cohorts",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
)

require_auth()
render_sync_sidebar()

st.title("Cohort Performance Report")

charges_df = load_charges()
subs_df = load_subscriptions()
orders_df = load_orders()
products_df = load_products()

if subs_df.empty:
    st.info("No subscription data yet. Run a sync from the sidebar.")
    st.stop()

# ------------------------------------------------------------------
# Filters
# ------------------------------------------------------------------

col_f1, col_f2, col_f3 = st.columns(3)

# Product filter — build a name-to-id map so we can pass product_id downstream
product_name_to_id: dict[str, str] = {}
product_options = ["All Products"]
if not products_df.empty and "name" in products_df.columns:
    for _, row in products_df[["id", "name"]].dropna().iterrows():
        name = str(row["name"])
        pid = str(row["id"])
        if name not in product_name_to_id:
            product_name_to_id[name] = pid
            product_options.append(name)
elif not subs_df.empty and "product_name" in subs_df.columns:
    # Fallback: derive from subscriptions (product_id + product_name)
    for _, row in subs_df[["product_id", "product_name"]].dropna().drop_duplicates("product_name").iterrows():
        name = str(row["product_name"])
        pid = str(row["product_id"])
        if name not in product_name_to_id:
            product_name_to_id[name] = pid
            product_options.append(name)

selected_product = col_f1.selectbox("Filter by Product", product_options)

# Interval filter
interval_options = ["All Intervals"]
if not subs_df.empty and "interval" in subs_df.columns:
    interval_options += subs_df["interval"].dropna().unique().tolist()
selected_interval = col_f2.selectbox("Filter by Interval", interval_options)

# Cohort view toggle
cohort_view = col_f3.radio(
    "Cohort View",
    options=["Combined", "Per-Period"],
    horizontal=True,
)

# Resolve filter values for analytics functions
product_filter: str | None = None
if selected_product != "All Products":
    product_filter = product_name_to_id.get(selected_product)

interval_filter: str | None = None
if selected_interval != "All Intervals":
    interval_filter = selected_interval

# ------------------------------------------------------------------
# Filter subscriptions for summary metrics
# ------------------------------------------------------------------

filtered_subs = subs_df.copy()
if product_filter is not None:
    filtered_subs = filtered_subs[
        filtered_subs["product_id"].astype(str) == str(product_filter)
    ]
if selected_interval != "All Intervals":
    filtered_subs = filtered_subs[
        filtered_subs["interval"] == selected_interval
    ]

if filtered_subs.empty:
    st.warning("No subscriptions match the selected filters.")
    st.stop()

# ------------------------------------------------------------------
# Summary metrics
# ------------------------------------------------------------------

total_subs = len(filtered_subs)
active_count = len(
    filtered_subs[filtered_subs["status"].str.lower() == "active"]
)
canceled_count = len(
    filtered_subs[
        filtered_subs["status"].str.lower().isin(["canceled", "cancelled"])
    ]
)
churn_pct = canceled_count / total_subs * 100 if total_subs > 0 else 0

mc1, mc2, mc3 = st.columns(3)
mc1.metric("Total Subscriptions", f"{total_subs:,}")
mc2.metric("Currently Active", f"{active_count:,}")
mc3.metric("Overall Churn Rate", f"{churn_pct:.1f}%")

# ------------------------------------------------------------------
# Detect dominant interval for period labels
# ------------------------------------------------------------------

_interval_to_prefix = {
    "weekly": "Week",
    "monthly": "Month",
    "yearly": "Year",
    "annual": "Year",
    "quarterly": "Quarter",
}


def _detect_period_prefix(subs: pd.DataFrame) -> str:
    """Return human label prefix based on the dominant subscription interval."""
    if subs.empty or "interval" not in subs.columns:
        return "Period"
    intervals = subs["interval"].dropna()
    if intervals.empty:
        return "Period"
    dominant = intervals.str.lower().value_counts().idxmax()
    return _interval_to_prefix.get(dominant, "Period")


period_prefix = _detect_period_prefix(filtered_subs)


def _add_period_label(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Insert a 'Period' display column at position 0."""
    out = df.copy()
    if "period" in out.columns:
        out.insert(0, "Period", out["period"].apply(lambda p: f"{prefix} {p}"))
    return out


# ------------------------------------------------------------------
# Section A: Activity Summary (Combined mode)
# ------------------------------------------------------------------

if cohort_view == "Combined":
    activity, renewal_rates, stick_rates = build_cohort_performance(
        charges_df,
        orders_df,
        subs_df,
        product_filter=product_filter,
        interval_filter=interval_filter,
    )

    if activity.empty:
        st.warning(
            "Not enough charge data to build cohort performance for the "
            "selected filters."
        )
        st.stop()

    # --- Section A: Activity Summary ---
    st.subheader("Activity Summary")
    display_activity = _add_period_label(activity, period_prefix)
    st.dataframe(
        display_activity,
        use_container_width=True,
        column_config={
            "period_revenue": st.column_config.NumberColumn(
                "Period Revenue", format="$%.2f"
            ),
            "cumulative_revenue": st.column_config.NumberColumn(
                "Cumulative Revenue", format="$%.2f"
            ),
        },
        hide_index=True,
    )
    render_export_buttons(
        display_activity, "cohort_activity_summary", key_prefix="activity"
    )

    # --- Section B: Period-over-Period Renewal Rate ---
    st.subheader("Period-over-Period Renewal Rate")
    if renewal_rates.empty:
        st.info("Not enough periods to compute renewal rates.")
    else:
        display_renewal = _add_period_label(renewal_rates, period_prefix)
        st.dataframe(
            display_renewal,
            use_container_width=True,
            column_config={
                "renewal_rate": st.column_config.NumberColumn(
                    "Renewal Rate %", format="%.1f%%"
                ),
                "stick_rate": st.column_config.NumberColumn(
                    "Stick Rate %", format="%.1f%%"
                ),
            },
            hide_index=True,
        )
        render_export_buttons(
            display_renewal, "cohort_renewal_rates", key_prefix="renewal"
        )

    # --- Section C: Cumulative Stick Rate & Refund Rate ---
    st.subheader("Cumulative Stick Rate & Refund Rate")
    if stick_rates.empty:
        st.info("Not enough data to compute stick rates.")
    else:
        display_stick = _add_period_label(stick_rates, period_prefix)
        st.dataframe(
            display_stick,
            use_container_width=True,
            column_config={
                "stick_rate": st.column_config.NumberColumn(
                    "Stick Rate %", format="%.1f%%"
                ),
                "refund_rate": st.column_config.NumberColumn(
                    "Refund Rate %", format="%.1f%%"
                ),
                "churn_refund_rate": st.column_config.NumberColumn(
                    "Churn+Refund Rate %", format="%.1f%%"
                ),
            },
            hide_index=True,
        )
        render_export_buttons(
            display_stick, "cohort_stick_rates", key_prefix="stick"
        )

# ------------------------------------------------------------------
# Section D: Retention Heatmap (Per-Period mode)
# ------------------------------------------------------------------

if cohort_view == "Per-Period":
    st.subheader("Retention Heatmap")
    st.caption(
        "Each cell shows the % of the cohort with a successful charge at "
        "that billing period."
    )

    heatmap_result = build_cohort_heatmap(
        charges_df,
        orders_df,
        subs_df,
        product_filter=product_filter,
        interval_filter=interval_filter,
    )

    if heatmap_result.empty:
        st.warning(
            "Not enough charge data to build a retention heatmap for the "
            "selected filters."
        )
        st.stop()

    # Separate cohort_size from period columns for the heatmap visual
    period_cols = [c for c in heatmap_result.columns if c != "cohort_size"]
    heatmap_data = heatmap_result[period_cols]

    # Rename columns with the detected interval prefix
    heatmap_data.columns = [
        f"{period_prefix} {c}" for c in heatmap_data.columns
    ]

    fig = px.imshow(
        heatmap_data.values,
        labels=dict(x="Billing Period", y="Cohort", color="Retention %"),
        x=heatmap_data.columns.tolist(),
        y=heatmap_data.index.tolist(),
        color_continuous_scale="RdYlGn",
        zmin=0,
        zmax=100,
        text_auto=".0f",
        aspect="auto",
    )
    fig.update_layout(height=max(400, len(heatmap_data) * 30))
    st.plotly_chart(fig, use_container_width=True)

    # Show raw table toggle
    if st.checkbox("Show raw retention table"):
        display_heatmap = heatmap_result.copy()
        display_heatmap.insert(
            0, "Cohort Size", display_heatmap.pop("cohort_size")
        )
        st.dataframe(display_heatmap, use_container_width=True)
        render_export_buttons(
            display_heatmap.reset_index(),
            "cohort_retention_heatmap",
            key_prefix="heatmap",
        )

# ------------------------------------------------------------------
# Methodology & Data Dictionary
# ------------------------------------------------------------------

render_doc_tabs(COHORT_RETENTION_METHODOLOGY)
