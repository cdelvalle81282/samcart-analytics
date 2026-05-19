"""SamCart Analytics Dashboard — Overview page."""

import logging

import pandas as pd
import plotly.express as px
import streamlit as st

from analytics import (
    arpu_by_product,
    customer_concentration,
    monthly_revenue_summary,
    net_revenue_retention,
    total_net_revenue,
)
from auth import is_admin, require_auth
from pii_access import check_pii_access
from export import cleanup_old_exports
from methodology import DASHBOARD_METHODOLOGY
from shared import load_charges, load_customers, load_orders, load_subscriptions, render_doc_tabs, render_sync_sidebar
from version import LAST_UPDATED, VERSION

logger = logging.getLogger(__name__)


def _mc(label: str, value: str, delta: str | None = None, neg: bool = False, help_text: str | None = None) -> str:
    """Render a custom HTML metric card matching the Electric Ledger aesthetic."""
    delta_html = ""
    if delta is not None:
        cls = "neg" if neg else "pos"
        delta_html = f'<div class="mc-delta {cls}">{delta}</div>'
    help_html = f'<div class="mc-help" title="{help_text}">?</div>' if help_text else ""
    return (
        f'<div class="mc">{help_html}'
        f'<div class="mc-label">{label}</div>'
        f'<div class="mc-value">{value}</div>'
        f'{delta_html}</div>'
    )


@st.cache_data(ttl=300)
def _cached_nrr(charges_df, subs_df):
    return net_revenue_retention(charges_df, subs_df)


@st.cache_data(ttl=300)
def _cached_arpu(subs_df):
    return arpu_by_product(subs_df)


@st.cache_data(ttl=300)
def _cached_concentration(charges_df):
    return customer_concentration(charges_df)


@st.cache_data(ttl=300)
def _cached_monthly_revenue(orders_df, charges_df):
    return monthly_revenue_summary(orders_df, charges_df)


require_auth()

render_sync_sidebar()

st.sidebar.markdown("---")
if st.sidebar.button("Clean Up Old Exports", use_container_width=True):
    deleted = cleanup_old_exports()
    if deleted:
        st.sidebar.success(f"Deleted {deleted} old export files")
    else:
        st.sidebar.info("No old exports to clean up")

st.title("Overview")
st.caption(f"Revenue, customers, and subscription health at a glance  ·  v{VERSION} · Updated {LAST_UPDATED}")

orders_df = load_orders()
subs_df = load_subscriptions()
customers_df = load_customers()
charges_df = load_charges()

if orders_df.empty and subs_df.empty:
    st.info("No data yet. Use the **Sync Data** button in the sidebar to fetch data from SamCart.")
    st.stop()

# ------------------------------------------------------------------
# Pre-compute all metric values
# ------------------------------------------------------------------

total_revenue = total_net_revenue(charges_df, orders_df)
total_customers = customers_df["id"].nunique() if not customers_df.empty else 0
active_subs = (
    subs_df[subs_df["status"].str.lower() == "active"]["id"].nunique()
    if not subs_df.empty
    else 0
)
avg_order = orders_df["total"].mean() if not orders_df.empty else 0

churn_rate = 0.0
if not subs_df.empty:
    total_subs = subs_df["id"].nunique()
    canceled = subs_df[subs_df["status"].str.lower().isin(["canceled", "cancelled"])]["id"].nunique()
    churn_rate = canceled / total_subs * 100 if total_subs > 0 else 0

monthly = _cached_monthly_revenue(orders_df, charges_df)

revenue_delta = None
if len(monthly) >= 2:
    revenue_delta = float(monthly.iloc[-1]["total_revenue"] - monthly.iloc[-2]["total_revenue"])

customers_delta = None
if not customers_df.empty and "created_at" in customers_df.columns:
    _cdf = customers_df.copy()
    _cdf["created_at"] = pd.to_datetime(_cdf["created_at"], errors="coerce", utc=True)
    _cdf = _cdf.dropna(subset=["created_at"])
    if not _cdf.empty:
        _cdf["month"] = _cdf["created_at"].dt.to_period("M")
        _counts = _cdf.groupby("month").size().sort_index()
        if len(_counts) >= 2:
            customers_delta = int(_counts.iloc[-1] - _counts.iloc[-2])

nrr_str = "N/A"
try:
    nrr_df = _cached_nrr(charges_df, subs_df)
    if not nrr_df.empty:
        _v = nrr_df.iloc[-1]["nrr_pct"]
        if pd.notna(_v):
            nrr_str = f"{_v:.1f}%"
except Exception:
    logger.exception("NRR computation failed on Overview")

avg_arpu = 0.0
try:
    arpu_df = _cached_arpu(subs_df)
    if not arpu_df.empty:
        _total_subs = arpu_df["active_subscribers"].sum()
        if _total_subs > 0:
            avg_arpu = float(
                (arpu_df["monthly_arpu"] * arpu_df["active_subscribers"]).sum() / _total_subs
            )
except Exception:
    logger.exception("ARPU computation failed on Overview")

top10_pct_str = "N/A"
try:
    conc_df = _cached_concentration(charges_df)
    if not conc_df.empty:
        _n = min(10, len(conc_df))
        top10_pct_str = f"{conc_df.iloc[_n - 1]['cumulative_pct']:.1f}%"
except Exception:
    logger.exception("Concentration computation failed on Overview")

# ------------------------------------------------------------------
# Metric cards — 2 rows of 4
# ------------------------------------------------------------------

r1c1, r1c2, r1c3, r1c4 = st.columns(4)
r2c1, r2c2, r2c3, r2c4 = st.columns(4)

_rev_delta_str = (
    f"+${revenue_delta:,.0f} MoM" if revenue_delta and revenue_delta > 0
    else (f"${revenue_delta:,.0f} MoM" if revenue_delta else None)
)
_cust_delta_str = (
    f"+{customers_delta:,} MoM" if customers_delta and customers_delta > 0
    else (f"{customers_delta:,} MoM" if customers_delta else None)
)

with r1c1:
    st.markdown(_mc("Total Revenue", f"${total_revenue:,.0f}", delta=_rev_delta_str,
        neg=revenue_delta is not None and revenue_delta < 0,
        help_text="Net revenue from collected charges minus partial refunds."), unsafe_allow_html=True)
with r1c2:
    st.markdown(_mc("Total Customers", f"{total_customers:,}", delta=_cust_delta_str,
        neg=customers_delta is not None and customers_delta < 0,
        help_text="Distinct customer records synced from SamCart."), unsafe_allow_html=True)
with r1c3:
    st.markdown(_mc("Active Subscriptions", f"{active_subs:,}",
        help_text="Subscriptions currently in 'active' status."), unsafe_allow_html=True)
with r1c4:
    st.markdown(_mc("Avg Order Value", f"${avg_order:,.2f}",
        help_text="Mean order total across all orders."), unsafe_allow_html=True)

with r2c1:
    st.markdown(_mc("Churn Rate", f"{churn_rate:.1f}%",
        help_text="Lifetime canceled subscriptions / total subscriptions."), unsafe_allow_html=True)
with r2c2:
    st.markdown(_mc("Net Revenue Retention", nrr_str,
        help_text="Last month's subscription revenue retained from prior-month customers. >100% = growing without new customers."), unsafe_allow_html=True)
with r2c3:
    st.markdown(_mc("Avg Monthly ARPU", f"${avg_arpu:,.2f}",
        help_text="Weighted average monthly revenue per active subscriber."), unsafe_allow_html=True)
with r2c4:
    st.markdown(_mc("Top 10 Concentration", top10_pct_str,
        help_text="Share of total revenue earned by your top 10 customers."), unsafe_allow_html=True)

st.markdown("")

# ------------------------------------------------------------------
# Monthly revenue chart
# ------------------------------------------------------------------

st.subheader("Monthly Revenue")
if not monthly.empty:
    fig = px.bar(
        monthly,
        x="month",
        y="total_revenue",
        text="order_count",
        labels={"total_revenue": "Revenue", "month": "Month", "order_count": "Orders"},
    )
    fig.update_traces(
        texttemplate="%{text} orders",
        textposition="outside",
        marker_color="#B8FF57",
        hovertemplate="<b>%{x}</b><br>Revenue: $%{y:,.0f}<br>Orders: %{text}<extra></extra>",
    )
    fig.update_layout(yaxis_tickformat="$,.0f", yaxis_title=None, xaxis_title=None, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No monthly data to display.")

# ------------------------------------------------------------------
# Recent orders
# ------------------------------------------------------------------

st.subheader("Recent Orders")
if not orders_df.empty:
    _user = st.session_state.get("username", "")
    _can_see_pii = is_admin(_user) or check_pii_access(_user)
    display_cols = ["created_at", "customer_email", "product_name", "total"] if _can_see_pii else ["created_at", "product_name", "total"]
    available_cols = [c for c in display_cols if c in orders_df.columns]
    st.dataframe(
        orders_df[available_cols].head(20),
        column_config={"total": st.column_config.NumberColumn("Total", format="$%.2f")},
        use_container_width=True,
    )

render_doc_tabs(DASHBOARD_METHODOLOGY)
