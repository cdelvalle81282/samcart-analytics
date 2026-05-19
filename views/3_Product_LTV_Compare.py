"""Report 3: Product LTV Comparison."""

import pandas as pd
import plotly.express as px
import streamlit as st

from analytics import to_eastern, product_ltv_ranking
from auth import require_auth, require_permission
from export import render_export_buttons
from methodology import PRODUCT_LTV_METHODOLOGY
from automate import render_automate_button
from shared import load_orders, load_products, load_subscriptions, render_doc_tabs, render_sync_sidebar


@st.cache_data(ttl=300)
def _cached_product_ltv(start_iso: str, end_iso: str):
    odf = load_orders().copy()
    odf["created_at"] = to_eastern(odf["created_at"])
    start = pd.Timestamp(start_iso).date()
    end = pd.Timestamp(end_iso).date()
    mask = (odf["created_at"].dt.date >= start) & (odf["created_at"].dt.date <= end)
    return product_ltv_ranking(odf[mask], load_subscriptions(), load_products())



require_auth()
require_permission("page:product_ltv")
render_sync_sidebar()

st.title("Product LTV Comparison")
st.caption("Which products generate the most revenue and the highest customer lifetime value.")


orders_df = load_orders()

if orders_df.empty:
    st.info("No data yet. Run a sync from the sidebar.")
    st.stop()

# ------------------------------------------------------------------
# Filters
# ------------------------------------------------------------------

col1, col2 = st.columns(2)

# Date range filter — convert to ET only for computing widget bounds
_created_et = to_eastern(orders_df["created_at"])
min_date = _created_et.min()
max_date = _created_et.max()

start, end = None, None
if pd.notna(min_date) and pd.notna(max_date):
    date_range = col1.date_input(
        "Date Range",
        value=(min_date.date(), max_date.date()),
        min_value=min_date.date(),
        max_value=max_date.date(),
    )
    if len(date_range) == 2:
        start, end = date_range

# Min order count filter
min_orders = col2.number_input("Min Order Count", min_value=0, value=0, step=1)

# ------------------------------------------------------------------
# Product ranking
# ------------------------------------------------------------------

if start is None or end is None:
    ranking = _cached_product_ltv(str(min_date.date()), str(max_date.date()))
else:
    ranking = _cached_product_ltv(str(start), str(end))

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

_ltv_date_range_days = (date_range[1] - date_range[0]).days if isinstance(date_range, (list, tuple)) and len(date_range) == 2 else 365
_ltv_filters_summary = f"{date_range[0] if isinstance(date_range, (list, tuple)) and len(date_range) == 2 else 'All'} | Min orders: {min_orders}"
render_automate_button(
    "product_ltv",
    "Product LTV Compare",
    _ltv_filters_summary,
    current_filters={"date_range_days": _ltv_date_range_days},
    extra_params={"min_orders": int(min_orders)} if min_orders > 0 else None,
)

# ------------------------------------------------------------------
# Documentation tabs
# ------------------------------------------------------------------

render_doc_tabs(PRODUCT_LTV_METHODOLOGY)
