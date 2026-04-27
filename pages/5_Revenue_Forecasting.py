"""Report 5: Revenue Forecasting — MRR waterfall, revenue forecast, and NRR trend."""

import logging

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analytics import mrr_waterfall, net_revenue_retention, revenue_forecast, upcoming_renewals_and_cancellations
from auth import is_admin, require_auth, require_permission
from export import render_export_buttons
from methodology import (
    MRR_WATERFALL_METHODOLOGY,
    NRR_METHODOLOGY,
    REVENUE_FORECAST_METHODOLOGY,
)
from automate import render_automate_button
from pii_access import check_pii_access
from shared import load_charges, load_subscriptions, render_doc_tabs, render_sync_sidebar

logger = logging.getLogger(__name__)


@st.cache_data(ttl=300)
def _cached_mrr_waterfall():
    return mrr_waterfall(load_subscriptions())


@st.cache_data(ttl=300)
def _cached_revenue_forecast():
    return revenue_forecast(load_subscriptions())


@st.cache_data(ttl=300)
def _cached_nrr():
    return net_revenue_retention(load_charges(), load_subscriptions())


@st.cache_data(ttl=300)
def _cached_upcoming(weeks: int):
    return upcoming_renewals_and_cancellations(load_subscriptions(), lookahead_weeks=weeks)



require_auth()
require_permission("page:revenue_forecast")
render_sync_sidebar()

st.title("Revenue Forecasting")

subs_df = load_subscriptions()

if subs_df.empty:
    st.info("No subscription data yet. Run a sync from the sidebar.")
    st.stop()

_user = st.session_state.get("username", "")
_can_see_pii = is_admin(_user) or check_pii_access(_user)

# ------------------------------------------------------------------
# Tabs
# ------------------------------------------------------------------

tab1, tab2, tab3 = st.tabs(["MRR Waterfall", "Revenue Forecast", "NRR Trend"])

# --- Tab 1: MRR Waterfall ---
with tab1:
    waterfall_df = _cached_mrr_waterfall()

    if waterfall_df.empty:
        st.warning("No MRR data available.")
    else:
        # Summary metrics — 5 columns: net, new, expansion, churn, reactivation, quick ratio
        latest = waterfall_df.iloc[-1]
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Latest Net MRR", f"${latest['net_mrr']:,.2f}",
                  help="New + Expansion + Reactivation MRR minus Churned MRR.")
        m2.metric("New MRR", f"${latest['new_mrr']:,.2f}",
                  help="Revenue from first-time subscribers to each product.")
        m3.metric("Expansion MRR", f"${latest['expansion_mrr']:,.2f}",
                  help="New subscriptions from customers who already have an active subscription to a different product.")
        m4.metric("Churned MRR", f"${latest['churned_mrr']:,.2f}",
                  help="Revenue lost from canceled subscriptions.")
        m5.metric("Reactivation MRR", f"${latest['reactivation_mrr']:,.2f}",
                  help="Revenue from customers who re-subscribed after a prior cancellation.")
        _qr = latest.get("quick_ratio", float("nan"))
        m6.metric("Quick Ratio", f"{_qr:.2f}" if pd.notna(_qr) else "N/A",
                  help="(New + Expansion + Reactivation) / Churned MRR. >1 = growing. >4 = excellent.")

        # Stacked bar chart with expansion
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=waterfall_df["month"], y=waterfall_df["new_mrr"],
            name="New MRR", marker_color="#2ecc71",
        ))
        fig.add_trace(go.Bar(
            x=waterfall_df["month"], y=waterfall_df["expansion_mrr"],
            name="Expansion MRR", marker_color="#1abc9c",
        ))
        fig.add_trace(go.Bar(
            x=waterfall_df["month"], y=waterfall_df["reactivation_mrr"],
            name="Reactivation MRR", marker_color="#9b59b6",
        ))
        fig.add_trace(go.Bar(
            x=waterfall_df["month"], y=-waterfall_df["churned_mrr"],
            name="Churned MRR", marker_color="#e74c3c",
        ))
        fig.add_trace(go.Scatter(
            x=waterfall_df["month"], y=waterfall_df["net_mrr"],
            name="Net MRR", mode="lines+markers", line={"color": "#3498db", "width": 2},
        ))
        fig.update_layout(
            barmode="relative",
            title="MRR Waterfall",
            yaxis_title="MRR ($)",
            yaxis_tickformat="$,.0f",
        )
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("MRR Data")
        st.dataframe(
            waterfall_df,
            column_config={
                "new_mrr": st.column_config.NumberColumn("New MRR", format="$%.2f"),
                "expansion_mrr": st.column_config.NumberColumn("Expansion MRR", format="$%.2f"),
                "contraction_mrr": st.column_config.NumberColumn("Contraction MRR", format="$%.2f"),
                "churned_mrr": st.column_config.NumberColumn("Churned MRR", format="$%.2f"),
                "reactivation_mrr": st.column_config.NumberColumn("Reactivation MRR", format="$%.2f"),
                "net_mrr": st.column_config.NumberColumn("Net MRR", format="$%.2f"),
                "quick_ratio": st.column_config.NumberColumn("Quick Ratio", format="%.2f"),
            },
            use_container_width=True,
        )
        render_export_buttons(waterfall_df, "mrr_waterfall", key_prefix="mrr_wf")

    render_automate_button("mrr_waterfall", "Revenue Forecasting — MRR Waterfall", "No filters")

    # ------------------------------------------------------------------
    # Upcoming Activity
    # ------------------------------------------------------------------

    st.markdown("---")
    st.subheader("Upcoming Activity")
    _window_label = st.radio(
        "Look-ahead window",
        options=["1 week", "4 weeks"],
        horizontal=True,
        key="upcoming_window",
    )
    _weeks = 1 if _window_label == "1 week" else 4
    try:
        upcoming = _cached_upcoming(_weeks)
    except Exception:
        logger.exception("Failed to load upcoming renewals")
        upcoming = {"renewals": pd.DataFrame(), "cancellations": pd.DataFrame()}

    def _show_upcoming(df: pd.DataFrame, empty_msg: str) -> None:
        if df.empty:
            st.info(empty_msg)
            return
        cols = ["product_name", "price", "days_until"]
        if _can_see_pii and "customer_email" in df.columns:
            cols = ["customer_email"] + cols
        st.dataframe(
            df[[c for c in cols if c in df.columns]],
            column_config={"price": st.column_config.NumberColumn("Price", format="$%.2f")},
            use_container_width=True,
        )

    uc1, uc2 = st.columns(2)
    with uc1:
        st.markdown("**Renewals**")
        _show_upcoming(upcoming.get("renewals", pd.DataFrame()), "No renewals scheduled in this window.")
    with uc2:
        st.markdown("**Cancellations**")
        _show_upcoming(upcoming.get("cancellations", pd.DataFrame()), "No cancellations scheduled in this window.")

# --- Tab 2: Revenue Forecast ---
with tab2:
    forecast_df = _cached_revenue_forecast()

    if forecast_df.empty:
        st.warning("No forecast data available. Ensure subscriptions have `next_bill_date` populated (requires a full sync).")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("30-Day Forecast", f"${forecast_df['forecast_30d'].sum():,.2f}")
        m2.metric("60-Day Forecast", f"${forecast_df['forecast_60d'].sum():,.2f}")
        m3.metric("90-Day Forecast", f"${forecast_df['forecast_90d'].sum():,.2f}")

        fig = px.bar(
            forecast_df,
            x="product_name",
            y=["forecast_30d", "forecast_60d", "forecast_90d"],
            barmode="group",
            labels={"value": "Projected Revenue ($)", "product_name": "Product", "variable": "Window"},
            title="Revenue Forecast by Product",
        )
        fig.update_layout(yaxis_tickformat="$,.0f")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Forecast Data")
        st.dataframe(
            forecast_df,
            column_config={
                "forecast_30d": st.column_config.NumberColumn("30-Day", format="$%.2f"),
                "forecast_60d": st.column_config.NumberColumn("60-Day", format="$%.2f"),
                "forecast_90d": st.column_config.NumberColumn("90-Day", format="$%.2f"),
            },
            use_container_width=True,
        )
        render_export_buttons(forecast_df, "revenue_forecast", key_prefix="rev_fc")

    render_automate_button("revenue_forecast", "Revenue Forecasting — Revenue Forecast", "No filters")

# --- Tab 3: NRR Trend ---
with tab3:
    nrr_df = _cached_nrr()

    if nrr_df.empty:
        st.info(
            "Need at least 2 months of subscription charge data to compute NRR. "
            "Run a full sync to populate historical charges."
        )
    else:
        latest_nrr = nrr_df.iloc[-1]
        _nrr_v = latest_nrr["nrr_pct"]
        nm1, nm2, nm3 = st.columns(3)
        nm1.metric(
            "Latest NRR",
            f"{_nrr_v:.1f}%" if pd.notna(_nrr_v) else "N/A",
            help="Net Revenue Retention for the most recent full month.",
        )
        nm2.metric(
            "Prior-Month Cohort MRR",
            f"${latest_nrr['starting_mrr']:,.0f}",
            help="Total subscription revenue from the prior-month subscriber cohort.",
        )
        nm3.metric(
            "Retained MRR",
            f"${latest_nrr['ending_mrr']:,.0f}",
            help="Revenue generated this month by those same prior-month subscribers.",
        )

        plot_df = nrr_df.dropna(subset=["nrr_pct"])
        if not plot_df.empty:
            fig_nrr = px.line(
                plot_df,
                x="month",
                y="nrr_pct",
                markers=True,
                labels={"nrr_pct": "NRR (%)", "month": "Month"},
                title="Net Revenue Retention Trend",
            )
            fig_nrr.add_hline(
                y=100,
                line_dash="dash",
                line_color="#7A8899",
                annotation_text="100% baseline",
                annotation_position="bottom right",
            )
            fig_nrr.update_layout(yaxis_ticksuffix="%")
            st.plotly_chart(fig_nrr, use_container_width=True)

        st.dataframe(
            nrr_df,
            column_config={
                "nrr_pct": st.column_config.NumberColumn("NRR %", format="%.1f%%"),
                "starting_mrr": st.column_config.NumberColumn("Prior-Month Cohort MRR", format="$%.0f"),
                "ending_mrr": st.column_config.NumberColumn("Retained MRR", format="$%.0f"),
            },
            use_container_width=True,
        )
        render_export_buttons(nrr_df, "nrr_trend", key_prefix="nrr")
        render_automate_button("nrr_trend", "Revenue Forecasting — NRR Trend", "No filters", key_suffix="nrr")

# ------------------------------------------------------------------
# Documentation
# ------------------------------------------------------------------

_COMBINED_METHODOLOGY = (
    MRR_WATERFALL_METHODOLOGY + "\n\n---\n\n"
    + REVENUE_FORECAST_METHODOLOGY + "\n\n---\n\n"
    + NRR_METHODOLOGY
)
render_doc_tabs(_COMBINED_METHODOLOGY)
