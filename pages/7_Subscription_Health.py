"""Report 7: Subscription Health — churn, trial conversion, aging."""

import plotly.express as px
import streamlit as st

from analytics import churn_analysis, subscription_aging, trial_conversion, trial_days_to_convert
from auth import require_auth, require_permission
from export import render_export_buttons
from methodology import (
    CHURN_ANALYSIS_METHODOLOGY,
    SUBSCRIPTION_AGING_METHODOLOGY,
    TRIAL_CONVERSION_METHODOLOGY,
)
from automate import render_automate_button
from shared import load_subscriptions, render_doc_tabs, render_sync_sidebar


@st.cache_data(ttl=300)
def _cached_churn_analysis():
    return churn_analysis(load_subscriptions())


@st.cache_data(ttl=300)
def _cached_trial_conversion():
    return trial_conversion(load_subscriptions())


@st.cache_data(ttl=300)
def _cached_subscription_aging():
    return subscription_aging(load_subscriptions())


@st.cache_data(ttl=300)
def _cached_trial_days_to_convert():
    return trial_days_to_convert(load_subscriptions())



require_auth()
require_permission("page:subscription_health")
render_sync_sidebar()

st.title("Subscription Health")
st.caption("Churn rates, trial-to-paid conversion, and subscription aging by product.")

subs_df = load_subscriptions()

if subs_df.empty:
    st.info("No subscription data yet. Run a sync from the sidebar.")
    st.stop()

# ------------------------------------------------------------------
# Tabs
# ------------------------------------------------------------------

tab1, tab2, tab3 = st.tabs(["Churn Analysis", "Trial-to-Paid", "Subscription Aging"])

# --- Tab 1: Churn Analysis ---
with tab1:
    by_product, monthly_trend = _cached_churn_analysis()

    if by_product.empty:
        st.warning("No churn data available.")
    else:
        # Summary metrics
        total_subs = by_product["total"].sum()
        total_canceled = by_product["canceled"].sum()
        overall_churn = total_canceled / total_subs * 100 if total_subs > 0 else 0
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Subscriptions", f"{total_subs:,}")
        m2.metric("Total Canceled", f"{total_canceled:,}")
        m3.metric("Overall Churn Rate", f"{overall_churn:.1f}%")

        # Churn rate by product
        st.subheader("Churn Rate by Product")
        fig = px.bar(
            by_product.sort_values("churn_rate"),
            x="churn_rate",
            y="product_name",
            orientation="h",
            labels={"churn_rate": "Churn Rate (%)", "product_name": "Product"},
        )
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            by_product,
            column_config={
                "churn_rate": st.column_config.NumberColumn("Churn Rate (%)", format="%.2f%%"),
                "avg_lifetime_days": st.column_config.NumberColumn("Avg Lifetime (days)", format="%.1f"),
            },
            use_container_width=True,
        )
        render_export_buttons(by_product, "churn_by_product", key_prefix="churn_prod")

    if not monthly_trend.empty:
        st.subheader("Monthly Trend")
        fig_trend = px.line(
            monthly_trend,
            x="month",
            y=["created", "canceled"],
            labels={"value": "Count", "month": "Month", "variable": "Type"},
            title="New vs Canceled Subscriptions",
            markers=True,
        )
        st.plotly_chart(fig_trend, use_container_width=True)

        fig_active = px.line(
            monthly_trend,
            x="month",
            y="cumulative_active",
            labels={"cumulative_active": "Cumulative Active", "month": "Month"},
            title="Cumulative Active Subscriptions",
            markers=True,
        )
        st.plotly_chart(fig_active, use_container_width=True)

    render_automate_button("subscription_health", "Subscription Health — Churn by Product", "No filters", key_suffix="churn")
    render_automate_button("subscription_health_churn_trend", "Subscription Health — Churn Trend", "No filters", key_suffix="churn_trend")
    st.markdown("---")
    st.markdown(CHURN_ANALYSIS_METHODOLOGY)

# --- Tab 2: Trial-to-Paid ---
with tab2:
    trial_df = _cached_trial_conversion()

    if trial_df.empty:
        st.warning("No trial data available. Ensure `trial_days` is populated (requires full sync).")
    else:
        # Summary metrics
        total_trials = trial_df["trial_count"].sum()
        total_converted = trial_df["converted"].sum()
        overall_conv = total_converted / total_trials * 100 if total_trials > 0 else 0
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Trials", f"{total_trials:,}")
        m2.metric("Converted", f"{total_converted:,}")
        m3.metric("Overall Conversion Rate", f"{overall_conv:.1f}%")

        fig = px.bar(
            trial_df.sort_values("conversion_rate_pct"),
            x="conversion_rate_pct",
            y="product_name",
            orientation="h",
            labels={"conversion_rate_pct": "Conversion Rate (%)", "product_name": "Product"},
            title="Trial-to-Paid Conversion by Product",
        )
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            trial_df,
            column_config={
                "conversion_rate_pct": st.column_config.NumberColumn("Conversion Rate (%)", format="%.2f%%"),
            },
            use_container_width=True,
        )
        render_export_buttons(trial_df, "trial_conversion", key_prefix="trial_conv")

        # Trial length distribution
        td_df = _cached_trial_days_to_convert()
        if not td_df.empty:
            st.subheader("Trial Length Distribution")
            st.caption("How long trials were for converted vs. dropped subscribers.")
            fig_td = px.histogram(
                td_df,
                x="trial_days",
                y="customer_count",
                color="outcome",
                barmode="group",
                histfunc="sum",
                color_discrete_map={"converted": "#10B981", "dropped": "#EF4444"},
                labels={
                    "trial_days": "Trial Days",
                    "customer_count": "Customers",
                    "outcome": "Outcome",
                },
            )
            st.plotly_chart(fig_td, use_container_width=True)
        else:
            st.info("No trial-length distribution data available. Requires a full sync with trial_days populated.")

    render_automate_button("subscription_health_trial", "Subscription Health — Trial-to-Paid", "No filters")
    st.markdown("---")
    st.markdown(TRIAL_CONVERSION_METHODOLOGY)

# --- Tab 3: Subscription Aging ---
with tab3:
    aging_df = _cached_subscription_aging()

    if aging_df.empty:
        st.warning("No active subscriptions for aging analysis.")
    else:
        # Overall donut
        overall = aging_df.groupby("age_bucket", observed=False)["count"].sum().reset_index()
        overall = overall[overall["count"] > 0]

        if not overall.empty:
            col1, col2 = st.columns(2)
            with col1:
                fig_donut = px.pie(
                    overall,
                    values="count",
                    names="age_bucket",
                    title="Overall Age Distribution",
                    hole=0.4,
                )
                st.plotly_chart(fig_donut, use_container_width=True)

            with col2:
                fig_bar = px.bar(
                    aging_df,
                    x="product_name",
                    y="count",
                    color="age_bucket",
                    barmode="stack",
                    labels={"count": "Subscriptions", "product_name": "Product", "age_bucket": "Age"},
                    title="Age Distribution by Product",
                )
                st.plotly_chart(fig_bar, use_container_width=True)

        st.dataframe(aging_df, use_container_width=True)
        render_export_buttons(aging_df, "subscription_aging", key_prefix="sub_aging")

    render_automate_button("subscription_health_aging", "Subscription Health — Subscription Aging", "No filters")
    st.markdown("---")
    st.markdown(SUBSCRIPTION_AGING_METHODOLOGY)

# ------------------------------------------------------------------
# Documentation
# ------------------------------------------------------------------

_COMBINED_METHODOLOGY = (
    CHURN_ANALYSIS_METHODOLOGY
    + "\n\n---\n\n"
    + TRIAL_CONVERSION_METHODOLOGY
    + "\n\n---\n\n"
    + SUBSCRIPTION_AGING_METHODOLOGY
)
render_doc_tabs(_COMBINED_METHODOLOGY)
