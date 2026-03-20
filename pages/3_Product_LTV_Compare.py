"""Report 3: Product LTV Comparison."""

import pandas as pd
import plotly.express as px
import streamlit as st

from analytics import _to_eastern, product_ltv_ranking
from auth import require_auth
from export import render_export_buttons
from methodology import API_DATA_DICTIONARY, PRODUCT_LTV_METHODOLOGY

from shared import get_cache

st.set_page_config(page_title="Product LTV Compare", page_icon=":package:", layout="wide")

require_auth()

st.title("Product LTV Comparison")


# ------------------------------------------------------------------
# Cached data loaders
# ------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_orders():
    return get_cache().get_orders_df()


@st.cache_data(ttl=300)
def load_subscriptions():
    return get_cache().get_subscriptions_df()


@st.cache_data(ttl=300)
def load_products():
    return get_cache().get_products_df()


orders_df = load_orders()
subs_df = load_subscriptions()
products_df = load_products()

if orders_df.empty:
    st.info("No data yet. Run a sync from the sidebar.")
    st.stop()

# ------------------------------------------------------------------
# Filters
# ------------------------------------------------------------------

col1, col2 = st.columns(2)

# Date range filter
orders_df["created_at"] = _to_eastern(orders_df["created_at"])
min_date = orders_df["created_at"].min()
max_date = orders_df["created_at"].max()

if pd.notna(min_date) and pd.notna(max_date):
    date_range = col1.date_input(
        "Date Range",
        value=(min_date.date(), max_date.date()),
        min_value=min_date.date(),
        max_value=max_date.date(),
    )
    if len(date_range) == 2:
        start, end = date_range
        mask = (orders_df["created_at"].dt.date >= start) & (orders_df["created_at"].dt.date <= end)
        orders_df = orders_df[mask]

# Min order count filter
min_orders = col2.number_input("Min Order Count", min_value=0, value=0, step=1)

# ------------------------------------------------------------------
# Product ranking
# ------------------------------------------------------------------

ranking = product_ltv_ranking(orders_df, subs_df, products_df)

if ranking.empty:
    st.warning("No product data to display.")
    st.stop()

# Apply min order filter
if min_orders > 0:
    ranking = ranking[ranking["order_count"] >= min_orders]

if ranking.empty:
    st.warning("No products meet the minimum order threshold.")
    st.stop()

# ------------------------------------------------------------------
# Chart
# ------------------------------------------------------------------

st.subheader("Products by Total Revenue")
fig = px.bar(
    ranking,
    x="product_name",
    y="total_revenue",
    text="order_count",
    labels={"total_revenue": "Total Revenue ($)", "product_name": "Product", "order_count": "Orders"},
    color="total_revenue",
    color_continuous_scale="Blues",
)
fig.update_traces(texttemplate="%{text} orders", textposition="outside")
fig.update_layout(yaxis_tickformat="$,.0f", showlegend=False)
st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------
# Detail table
# ------------------------------------------------------------------

st.subheader("Product Details")

display_df = ranking[[
    "product_name", "total_revenue", "order_count",
    "avg_order_value", "subscriber_count", "avg_lifetime_months",
]].copy()

display_df.columns = [
    "Product", "Total Revenue", "Orders",
    "Avg Order Value", "Subscribers", "Avg Lifetime (months)",
]

# Format currency columns for display
st.dataframe(
    display_df.style.format({
        "Total Revenue": "${:,.2f}",
        "Avg Order Value": "${:,.2f}",
        "Avg Lifetime (months)": "{:.1f}",
    }),
    use_container_width=True,
)

render_export_buttons(ranking, "product_ltv", key_prefix="product")

# ------------------------------------------------------------------
# Documentation tabs
# ------------------------------------------------------------------

st.markdown("---")
doc_tab1, doc_tab2 = st.tabs(["How It's Calculated", "Available Data Points"])
with doc_tab1:
    st.markdown(PRODUCT_LTV_METHODOLOGY)
with doc_tab2:
    st.markdown(API_DATA_DICTIONARY)
