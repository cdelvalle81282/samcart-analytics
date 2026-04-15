"""Report 6: Refund Analysis — rates, time-to-refund, trends."""

import plotly.express as px
import streamlit as st

from analytics import refund_analysis
from auth import require_auth, require_permission
from export import render_export_buttons
from methodology import REFUND_ANALYSIS_METHODOLOGY
from automate import render_automate_button
from shared import load_charges, load_orders, load_subscriptions, render_doc_tabs, render_sync_sidebar

st.set_page_config(page_title="Refund Analysis", page_icon=":money_with_wings:", layout="wide")

require_auth()
require_permission("page:refund_analysis")
render_sync_sidebar()

st.title("Refund Analysis")

charges_df = load_charges()
orders_df = load_orders()
subs_df = load_subscriptions()

if charges_df.empty:
    st.info("No charge data yet. Run a sync from the sidebar.")
    st.stop()

by_product, time_to_refund, monthly_trend = refund_analysis(charges_df, orders_df, subs_df)

if by_product.empty:
    st.warning("No refund data available.")
    st.stop()

# ------------------------------------------------------------------
# Summary metrics
# ------------------------------------------------------------------

m1, m2, m3 = st.columns(3)
m1.metric("Total Refunds", f"{by_product['refund_count'].sum():,}")
m2.metric("Total Refund Amount", f"${by_product['refund_amount'].sum():,.2f}")
overall_rate = (
    by_product["refund_count"].sum() / by_product["gross_charge_count"].sum() * 100
    if by_product["gross_charge_count"].sum() > 0 else 0
)
m3.metric("Overall Refund Rate", f"{overall_rate:.1f}%")

# ------------------------------------------------------------------
# Refund rate by product
# ------------------------------------------------------------------

st.subheader("Refund Rate by Product")
fig = px.bar(
    by_product.sort_values("refund_rate_count_pct"),
    x="refund_rate_count_pct",
    y="product_name",
    orientation="h",
    labels={"refund_rate_count_pct": "Refund Rate (%)", "product_name": "Product"},
    title="Refund Rate by Product (Count %)",
)
st.plotly_chart(fig, use_container_width=True)

st.dataframe(
    by_product,
    column_config={
        "gross_revenue": st.column_config.NumberColumn("Gross Revenue", format="$%.2f"),
        "refund_amount": st.column_config.NumberColumn("Refund Amount", format="$%.2f"),
        "refund_rate_count_pct": st.column_config.NumberColumn("Refund Rate (Count %)", format="%.2f%%"),
        "refund_rate_revenue_pct": st.column_config.NumberColumn("Refund Rate (Revenue %)", format="%.2f%%"),
    },
    use_container_width=True,
)
render_export_buttons(by_product, "refund_by_product", key_prefix="ref_prod")
render_automate_button("refund_analysis", "Refund Analysis — By Product", "No filters", key_suffix="by_product")

# ------------------------------------------------------------------
# Time to refund
# ------------------------------------------------------------------

st.subheader("Time to Refund")
if not time_to_refund.empty:
    fig_ttf = px.histogram(
        time_to_refund,
        x="days_to_refund",
        nbins=30,
        labels={"days_to_refund": "Days to Refund"},
        title="Distribution of Days to Refund",
    )
    st.plotly_chart(fig_ttf, use_container_width=True)

    m1, m2, m3 = st.columns(3)
    m1.metric("Avg Days to Refund", f"{time_to_refund['days_to_refund'].mean():.1f}")
    m2.metric("Median Days to Refund", f"{time_to_refund['days_to_refund'].median():.0f}")
    m3.metric("Max Days to Refund", f"{time_to_refund['days_to_refund'].max():.0f}")
else:
    st.info("No time-to-refund data available. Ensure `refund_date` is populated (requires full charge sync).")
render_automate_button("refund_time_to_refund", "Refund Analysis — Time to Refund", "No filters")

# ------------------------------------------------------------------
# Monthly refund trend
# ------------------------------------------------------------------

st.subheader("Monthly Refund Trend")
if not monthly_trend.empty:
    fig_trend = px.line(
        monthly_trend,
        x="month",
        y="refund_count",
        labels={"refund_count": "Refund Count", "month": "Month"},
        title="Monthly Refund Count",
        markers=True,
    )
    st.plotly_chart(fig_trend, use_container_width=True)

    fig_amt = px.line(
        monthly_trend,
        x="month",
        y="refund_amount",
        labels={"refund_amount": "Refund Amount ($)", "month": "Month"},
        title="Monthly Refund Amount",
        markers=True,
    )
    fig_amt.update_layout(yaxis_tickformat="$,.0f")
    st.plotly_chart(fig_amt, use_container_width=True)
else:
    st.info("No monthly refund trend data available.")
render_automate_button("refund_monthly_trend", "Refund Analysis — Monthly Trend", "No filters")

# ------------------------------------------------------------------
# Documentation
# ------------------------------------------------------------------

render_doc_tabs(REFUND_ANALYSIS_METHODOLOGY)
