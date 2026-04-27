"""SamCart Analytics Dashboard — main entry point with sync controls and overview."""

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


st.set_page_config(
    page_title="SamCart Analytics",
    page_icon=":bar_chart:",
    layout="wide",
)

require_auth()

# ------------------------------------------------------------------
# Sidebar — sync controls
# ------------------------------------------------------------------

render_sync_sidebar()

# Export cleanup (Dashboard-only extra)
st.sidebar.markdown("---")
if st.sidebar.button("Clean Up Old Exports", use_container_width=True):
    deleted = cleanup_old_exports()
    if deleted:
        st.sidebar.success(f"Deleted {deleted} old export files")
    else:
        st.sidebar.info("No old exports to clean up")


# ------------------------------------------------------------------
# Main dashboard
# ------------------------------------------------------------------

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

# Monthly revenue summary — used for chart AND revenue delta
monthly = _cached_monthly_revenue(orders_df, charges_df)

# Revenue delta MoM
revenue_delta = None
if len(monthly) >= 2:
    revenue_delta = float(monthly.iloc[-1]["total_revenue"] - monthly.iloc[-2]["total_revenue"])

# New customers delta MoM
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

# NRR — latest month
nrr_str = "N/A"
try:
    nrr_df = _cached_nrr(charges_df, subs_df)
    if not nrr_df.empty:
        _v = nrr_df.iloc[-1]["nrr_pct"]
        if pd.notna(_v):
            nrr_str = f"{_v:.1f}%"
except Exception:
    logger.exception("NRR computation failed on Overview")

# Weighted ARPU across all active subscribers
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

# Revenue concentration — top 10 customers
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

r1c1.metric(
    "Total Revenue",
    f"${total_revenue:,.2f}",
    delta=f"${revenue_delta:+,.0f} MoM" if revenue_delta is not None else None,
    help="Net revenue from collected charges minus partial refunds.",
)
r1c2.metric(
    "Total Customers",
    f"{total_customers:,}",
    delta=f"{customers_delta:+,} MoM" if customers_delta is not None else None,
    help="Distinct customer records synced from SamCart.",
)
r1c3.metric(
    "Active Subscriptions",
    f"{active_subs:,}",
    help="Subscriptions currently in 'active' status.",
)
r1c4.metric(
    "Avg Order Value",
    f"${avg_order:,.2f}",
    help="Mean order total across all orders.",
)
r2c1.metric(
    "Churn Rate",
    f"{churn_rate:.1f}%",
    help="Lifetime canceled subscriptions / total subscriptions.",
)
r2c2.metric(
    "Net Revenue Retention",
    nrr_str,
    help="Last month's subscription revenue retained from prior-month customers, as a % of their prior-month revenue. >100% = growing without new customers.",
)
r2c3.metric(
    "Avg Monthly ARPU",
    f"${avg_arpu:,.2f}",
    help="Weighted average monthly revenue per active subscriber across all products.",
)
r2c4.metric(
    "Top 10 Concentration",
    top10_pct_str,
    help="Share of total customer revenue earned by your top 10 customers.",
)

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
        marker_color="#4F90F0",
        hovertemplate="<b>%{x}</b><br>Revenue: $%{y:,.0f}<br>Orders: %{text}<extra></extra>",
    )
    fig.update_layout(
        yaxis_tickformat="$,.0f",
        yaxis_title=None,
        xaxis_title=None,
        showlegend=False,
    )
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

# ------------------------------------------------------------------
# Documentation tabs
# ------------------------------------------------------------------

render_doc_tabs(DASHBOARD_METHODOLOGY)
