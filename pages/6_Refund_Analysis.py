"""Report 6: Refund Analysis — rates, time-to-refund, trends, and failed payments."""

import plotly.express as px
import streamlit as st

from analytics import failed_payment_analysis, refund_analysis
from auth import require_auth, require_permission
from export import render_export_buttons
from methodology import FAILED_PAYMENT_METHODOLOGY, REFUND_ANALYSIS_METHODOLOGY
from automate import render_automate_button
from shared import load_charges, load_orders, load_subscriptions, render_doc_tabs, render_sync_sidebar


@st.cache_data(ttl=300)
def _cached_refund_analysis():
    return refund_analysis(load_charges(), load_orders(), load_subscriptions())


@st.cache_data(ttl=300)
def _cached_failed_payments():
    return failed_payment_analysis(load_charges(), load_orders(), load_subscriptions())



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

by_product, time_to_refund, monthly_trend = _cached_refund_analysis()

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
# Failed Payments
# ------------------------------------------------------------------

st.markdown("---")
st.subheader("Failed Payments")
st.caption("Charges that were attempted but not collected — distinct from refunds.")

by_month_f, by_product_f = _cached_failed_payments()
_total_failed = int(by_month_f["failed_count"].sum()) if not by_month_f.empty else 0
_total_failed_amt = float(by_month_f["failed_amount"].sum()) if not by_month_f.empty else 0.0
_total_charge_count = int(by_month_f["total_charge_count"].sum()) if not by_month_f.empty else 0
_overall_failure_rate = (
    _total_failed / _total_charge_count * 100 if _total_charge_count > 0 else 0.0
)

fm1, fm2, fm3 = st.columns(3)
fm1.metric(
    "Failed Charges",
    f"{_total_failed:,}",
    help="Charges with a non-successful, non-refund status (e.g., declined, failed).",
)
fm2.metric(
    "Failed Amount",
    f"${_total_failed_amt:,.2f}",
    help="Sum of attempted charge amounts that failed to collect.",
)
fm3.metric(
    "Failure Rate",
    f"{_overall_failure_rate:.2f}%",
    help="Failed charges as % of all charge attempts. Industry benchmark: 5–10%.",
)

if not by_month_f.empty and _total_failed > 0:
    fig_fc = px.line(
        by_month_f,
        x="month",
        y="failed_count",
        markers=True,
        labels={"failed_count": "Failed Charges", "month": "Month"},
        title="Failed Charges by Month",
    )
    st.plotly_chart(fig_fc, use_container_width=True)

    fig_fr = px.line(
        by_month_f,
        x="month",
        y="failure_rate_pct",
        markers=True,
        labels={"failure_rate_pct": "Failure Rate (%)", "month": "Month"},
        title="Failure Rate by Month",
    )
    fig_fr.update_layout(yaxis_ticksuffix="%")
    st.plotly_chart(fig_fr, use_container_width=True)

    if not by_product_f.empty:
        st.subheader("Failed Payments by Product")
        st.dataframe(
            by_product_f,
            column_config={
                "failed_amount": st.column_config.NumberColumn("Failed Amount", format="$%.2f"),
                "failure_rate_pct": st.column_config.NumberColumn("Failure Rate", format="%.2f%%"),
            },
            use_container_width=True,
        )
        render_export_buttons(by_product_f, "failed_payments_by_product", key_prefix="failed_prod")
else:
    st.info("No failed payment records found. All charge attempts appear to have succeeded or resulted in refunds.")

render_automate_button(
    "failed_payments",
    "Refund Analysis — Failed Payments",
    "No filters",
    key_suffix="failed",
)

# ------------------------------------------------------------------
# Documentation
# ------------------------------------------------------------------

_COMBINED_METHODOLOGY = REFUND_ANALYSIS_METHODOLOGY + "\n\n---\n\n" + FAILED_PAYMENT_METHODOLOGY
render_doc_tabs(_COMBINED_METHODOLOGY)
