"""SamCart Analytics Dashboard — main entry point with sync controls and overview."""

import logging

import plotly.express as px
import streamlit as st

from analytics import monthly_revenue_summary, total_net_revenue
from auth import is_admin, require_auth
from pii_access import check_pii_access
from export import cleanup_old_exports
from methodology import DASHBOARD_METHODOLOGY
from shared import load_charges, load_customers, load_orders, load_subscriptions, render_doc_tabs, render_sync_sidebar
from version import LAST_UPDATED, VERSION

logger = logging.getLogger(__name__)

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
# Metric row — all 5 KPIs in one line
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

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Revenue", f"${total_revenue:,.2f}")
col2.metric("Total Customers", f"{total_customers:,}")
col3.metric("Active Subscriptions", f"{active_subs:,}")
col4.metric("Avg Order Value", f"${avg_order:,.2f}")
col5.metric("Overall Churn Rate", f"{churn_rate:.1f}%")

st.markdown("")

# ------------------------------------------------------------------
# Monthly revenue chart
# ------------------------------------------------------------------

st.subheader("Monthly Revenue")
monthly = monthly_revenue_summary(orders_df, charges_df)
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
