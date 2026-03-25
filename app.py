"""SamCart Analytics Dashboard — main entry point with sync controls and overview."""

import logging

import plotly.express as px
import streamlit as st

from analytics import monthly_revenue_summary
from auth import is_admin, require_auth
from pii_access import check_pii_access
from export import cleanup_old_exports
from methodology import API_DATA_DICTIONARY, DASHBOARD_METHODOLOGY
from samcart_api import SamCartAPIError
from shared import get_cache, get_client
from version import LAST_UPDATED, VERSION

logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="SamCart Analytics",
    page_icon=":bar_chart:",
    layout="wide",
)

require_auth()

st.caption(f"v{VERSION} | Last App Update: {LAST_UPDATED}")

# ------------------------------------------------------------------
# Sidebar — sync controls
# ------------------------------------------------------------------

st.sidebar.title("SamCart Analytics")

client = get_client()
cache = get_cache()

# Credential check
if not client.api_key or client.api_key == "sc_live_YOUR_KEY_HERE":
    st.sidebar.error("Set your API key in `.streamlit/secrets.toml`")
else:
    try:
        if client.verify_credentials():
            st.sidebar.success("Connected to SamCart")
        else:
            st.sidebar.error("Invalid API key")
    except Exception:
        logger.exception("API key verification failed")
        st.sidebar.warning("Could not verify API key. Check your configuration.")

# Sync controls
st.sidebar.markdown("---")
st.sidebar.subheader("Data Sync")

force_full = st.sidebar.checkbox("Force full resync", value=False)
sync_btn = st.sidebar.button(
    "Sync Data",
    disabled=st.session_state.get("sync_running", False),
    use_container_width=True,
)

if sync_btn:
    st.session_state.sync_running = True
    try:
        with st.sidebar:
            valid = client.verify_credentials()
            if not valid:
                st.error("Invalid API key — cannot sync")
            else:
                total = cache.sync_all(client, force_full=force_full)
                st.success(f"Synced {total:,} records")
                # Clear cached DataFrames so pages get fresh data
                st.cache_data.clear()
    except SamCartAPIError:
        logger.exception("SamCart API error during sync")
        st.sidebar.error("Sync failed due to an API error. Check logs for details.")
    except Exception:
        logger.exception("Unexpected error during sync")
        st.sidebar.error("Sync failed unexpectedly. Check logs for details.")
    finally:
        st.session_state.sync_running = False

# Sync summary
summary = cache.get_sync_summary()
if summary:
    st.sidebar.markdown("---")
    st.sidebar.subheader("Cache Status")
    for table, meta in sorted(summary.items()):
        last = meta["last_synced_at"] or "Never"
        count = meta["record_count"] or 0
        st.sidebar.caption(f"**{table}**: {count:,} records (synced {last[:16]})")

# Export cleanup
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

st.title("Dashboard")

# Load data with caching
@st.cache_data(ttl=300)
def load_orders():
    return get_cache().get_orders_df()

@st.cache_data(ttl=300)
def load_subscriptions():
    return get_cache().get_subscriptions_df()

@st.cache_data(ttl=300)
def load_customers():
    return get_cache().get_customers_df()

@st.cache_data(ttl=300)
def load_charges():
    return get_cache().get_charges_df()


orders_df = load_orders()
subs_df = load_subscriptions()
customers_df = load_customers()
charges_df = load_charges()

if orders_df.empty and subs_df.empty:
    st.info("No data yet. Use the **Sync Data** button in the sidebar to fetch data from SamCart.")
    st.stop()

# Metric cards
col1, col2, col3, col4 = st.columns(4)

if not charges_df.empty:
    from analytics import _is_collected_charge, _net_charge_amount
    _collected = charges_df[_is_collected_charge(charges_df["status"])].copy()
    _collected["net_amount"] = _net_charge_amount(_collected)
    total_revenue = _collected["net_amount"].sum()
else:
    total_revenue = orders_df["total"].sum() if not orders_df.empty else 0
total_customers = customers_df["id"].nunique() if not customers_df.empty else 0
active_subs = (
    subs_df[subs_df["status"].str.lower() == "active"]["id"].nunique()
    if not subs_df.empty
    else 0
)
avg_order = orders_df["total"].mean() if not orders_df.empty else 0

col1.metric("Total Revenue", f"${total_revenue:,.2f}")
col2.metric("Total Customers", f"{total_customers:,}")
col3.metric("Active Subscriptions", f"{active_subs:,}")
col4.metric("Avg Order Value", f"${avg_order:,.2f}")

# Churn rate
if not subs_df.empty:
    total_subs = subs_df["id"].nunique()
    canceled = subs_df[subs_df["status"].str.lower().isin(["canceled", "cancelled"])]["id"].nunique()
    churn_rate = canceled / total_subs * 100 if total_subs > 0 else 0
    st.metric("Overall Churn Rate", f"{churn_rate:.1f}%")

# Monthly revenue chart
st.subheader("Monthly Revenue")
monthly = monthly_revenue_summary(orders_df, charges_df)
if not monthly.empty:
    fig = px.bar(
        monthly,
        x="month",
        y="total_revenue",
        text="order_count",
        labels={"total_revenue": "Revenue ($)", "month": "Month", "order_count": "Orders"},
    )
    fig.update_traces(texttemplate="%{text} orders", textposition="outside")
    fig.update_layout(yaxis_tickformat="$,.0f")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No monthly data to display.")

# Recent orders
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

st.markdown("---")
doc_tab1, doc_tab2 = st.tabs(["How It's Calculated", "Available Data Points"])
with doc_tab1:
    st.markdown(DASHBOARD_METHODOLOGY)
with doc_tab2:
    st.markdown(API_DATA_DICTIONARY)
