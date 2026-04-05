"""Report 4: Daily Metrics — new customers, sales, refunds, renewals by product."""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st

from analytics import (
    build_daily_summary,
    new_customer_ltv_by_entry_product,
)
from auth import require_auth, require_permission
from export import render_export_buttons
from methodology import DAILY_METRICS_METHODOLOGY
from shared import load_charges, load_orders, load_subscriptions, render_doc_tabs, render_sync_sidebar

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Daily Metrics", page_icon=":chart_with_upwards_trend:", layout="wide")

require_auth()
require_permission("page:daily_metrics")
render_sync_sidebar()

st.title("Daily Metrics")

orders_df = load_orders()
charges_df = load_charges()
subs_df = load_subscriptions()

if orders_df.empty and charges_df.empty:
    st.info("No data yet. Run a sync from the sidebar.")
    st.stop()

# ------------------------------------------------------------------
# Build summary data
# ------------------------------------------------------------------

summary_df = build_daily_summary(orders_df, charges_df, subs_df)

if summary_df.empty:
    st.warning("No daily metrics data available.")
    st.stop()

# ------------------------------------------------------------------
# Filters
# ------------------------------------------------------------------

col_f1, col_f2 = st.columns(2)

products = sorted(summary_df["product_name"].dropna().unique().tolist())
selected_products = col_f1.multiselect(
    "Products",
    options=products,
    default=products,
    key="daily_product_filter",
)

min_date = summary_df["date"].min().date() if hasattr(summary_df["date"].min(), "date") else summary_df["date"].min()
today_et = datetime.now(ZoneInfo("America/New_York")).date()
data_max = summary_df["date"].max().date() if hasattr(summary_df["date"].max(), "date") else summary_df["date"].max()
max_date = min(data_max, today_et)
default_start = max(min_date, max_date - timedelta(days=30))

date_range = col_f2.date_input(
    "Date range",
    value=(default_start, max_date),
    min_value=min_date,
    max_value=max_date,
    key="daily_date_range",
)

# Apply filters
filtered = summary_df.copy()
if selected_products:
    filtered = filtered[filtered["product_name"].isin(selected_products)]
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    start, end = date_range
    filtered = filtered[
        (filtered["date"].dt.date >= start) & (filtered["date"].dt.date <= end)
    ]

if filtered.empty:
    st.warning("No data matches the selected filters.")
    st.stop()

# ------------------------------------------------------------------
# Summary metrics row
# ------------------------------------------------------------------

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total New Customers", f"{int(filtered['new_customer_count'].sum()):,}")
m2.metric("Total New Sales", f"{int(filtered['sale_count'].sum()):,}")
m3.metric("Total Refunds", f"{int(filtered['refund_count'].sum()):,}")
m4.metric("Total Renewals", f"{int(filtered['renewal_count'].sum()):,}")

# ------------------------------------------------------------------
# Tabs
# ------------------------------------------------------------------

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Daily Summary",
    "New Customers Trend",
    "New Sales Trend",
    "Refunds Trend",
    "Renewals Trend",
    "Entry Product LTV",
])

# --- Tab 1: Daily Summary Table ---
with tab1:
    display_df = filtered.copy()
    display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
    st.dataframe(
        display_df,
        column_config={
            "sale_revenue": st.column_config.NumberColumn("Sale Revenue", format="$%.2f"),
            "refund_amount": st.column_config.NumberColumn("Refund Amount", format="$%.2f"),
            "renewal_revenue": st.column_config.NumberColumn("Renewal Revenue", format="$%.2f"),
        },
        use_container_width=True,
    )
    # Export version includes totals row
    totals = {col: "" for col in display_df.columns}
    totals["date"] = "TOTAL"
    totals["product_name"] = ""
    for col in ["new_customer_count", "sale_count", "sale_revenue",
                "refund_count", "refund_amount", "renewal_count", "renewal_revenue"]:
        if col in display_df.columns:
            totals[col] = display_df[col].sum()
    export_df = pd.concat([display_df, pd.DataFrame([totals])], ignore_index=True)
    render_export_buttons(export_df, "daily_summary", key_prefix="daily_summary")

# --- Tab 2: New Customers Trend ---
with tab2:
    daily_nc = (
        filtered.groupby(["date", "product_name"])["new_customer_count"]
        .sum()
        .reset_index()
    )
    if not daily_nc.empty:
        fig = px.line(
            daily_nc,
            x="date",
            y="new_customer_count",
            color="product_name",
            labels={"new_customer_count": "New Customers", "date": "Date", "product_name": "Product"},
            title="New Customers by Product",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No new customer data for selected filters.")

# --- Tab 3: New Sales Trend ---
with tab3:
    daily_ns = (
        filtered.groupby(["date", "product_name"])
        .agg(sale_count=("sale_count", "sum"), sale_revenue=("sale_revenue", "sum"))
        .reset_index()
    )
    if not daily_ns.empty:
        fig_count = px.line(
            daily_ns,
            x="date",
            y="sale_count",
            color="product_name",
            labels={"sale_count": "Sales Count", "date": "Date", "product_name": "Product"},
            title="New Sales Count by Product",
        )
        st.plotly_chart(fig_count, use_container_width=True)

        fig_rev = px.line(
            daily_ns,
            x="date",
            y="sale_revenue",
            color="product_name",
            labels={"sale_revenue": "Revenue ($)", "date": "Date", "product_name": "Product"},
            title="New Sales Revenue by Product",
        )
        fig_rev.update_layout(yaxis_tickformat="$,.0f")
        st.plotly_chart(fig_rev, use_container_width=True)
    else:
        st.info("No new sales data for selected filters.")

# --- Tab 4: Refunds Trend ---
with tab4:
    daily_ref = (
        filtered.groupby(["date", "product_name"])
        .agg(refund_count=("refund_count", "sum"), refund_amount=("refund_amount", "sum"))
        .reset_index()
    )
    if not daily_ref.empty:
        fig_rc = px.line(
            daily_ref,
            x="date",
            y="refund_count",
            color="product_name",
            labels={"refund_count": "Refund Count", "date": "Date", "product_name": "Product"},
            title="Refund Count by Product",
        )
        st.plotly_chart(fig_rc, use_container_width=True)

        fig_ra = px.line(
            daily_ref,
            x="date",
            y="refund_amount",
            color="product_name",
            labels={"refund_amount": "Refund Amount ($)", "date": "Date", "product_name": "Product"},
            title="Refund Amount by Product",
        )
        fig_ra.update_layout(yaxis_tickformat="$,.0f")
        st.plotly_chart(fig_ra, use_container_width=True)
    else:
        st.info("No refund data for selected filters.")

# --- Tab 5: Renewals Trend ---
with tab5:
    daily_ren = (
        filtered.groupby(["date", "product_name"])
        .agg(renewal_count=("renewal_count", "sum"), renewal_revenue=("renewal_revenue", "sum"))
        .reset_index()
    )
    if not daily_ren.empty:
        fig_renc = px.line(
            daily_ren,
            x="date",
            y="renewal_count",
            color="product_name",
            labels={"renewal_count": "Renewal Count", "date": "Date", "product_name": "Product"},
            title="Renewal Count by Product",
        )
        st.plotly_chart(fig_renc, use_container_width=True)

        fig_renr = px.line(
            daily_ren,
            x="date",
            y="renewal_revenue",
            color="product_name",
            labels={"renewal_revenue": "Revenue ($)", "date": "Date", "product_name": "Product"},
            title="Renewal Revenue by Product",
        )
        fig_renr.update_layout(yaxis_tickformat="$,.0f")
        st.plotly_chart(fig_renr, use_container_width=True)
    else:
        st.info("No renewal data for selected filters.")

# --- Tab 6: Entry Product LTV ---
with tab6:
    ltv_start = date_range[0] if isinstance(date_range, (list, tuple)) and len(date_range) == 2 else None
    ltv_end = date_range[1] if isinstance(date_range, (list, tuple)) and len(date_range) == 2 else None
    ltv_df = new_customer_ltv_by_entry_product(
        orders_df, charges_df, subs_df, start_date=ltv_start, end_date=ltv_end,
    )
    if selected_products:
        ltv_df = ltv_df[ltv_df["product_name"].isin(selected_products)]
    if not ltv_df.empty:
        fig_ltv = px.bar(
            ltv_df,
            x="product_name",
            y="avg_ltv",
            text="customer_count",
            labels={"avg_ltv": "Average LTV ($)", "product_name": "Entry Product", "customer_count": "Customers"},
            title="Average LTV by Entry Product",
        )
        fig_ltv.update_traces(texttemplate="%{text} customers", textposition="outside")
        fig_ltv.update_layout(yaxis_tickformat="$,.0f")
        st.plotly_chart(fig_ltv, use_container_width=True)

        st.subheader("LTV Details")
        st.dataframe(
            ltv_df,
            column_config={
                "avg_ltv": st.column_config.NumberColumn("Avg LTV", format="$%.2f"),
                "median_ltv": st.column_config.NumberColumn("Median LTV", format="$%.2f"),
                "total_ltv": st.column_config.NumberColumn("Total LTV", format="$%.2f"),
            },
            use_container_width=True,
        )
        render_export_buttons(ltv_df, "entry_product_ltv", key_prefix="entry_ltv")
    else:
        st.info("No LTV data available.")

# ------------------------------------------------------------------
# Google Sheets upload
# ------------------------------------------------------------------

st.markdown("---")
st.subheader("Google Sheets Upload")

try:
    sheets_config = st.secrets.get("gsheets", None)
except Exception:
    sheets_config = None

if sheets_config and sheets_config.get("spreadsheet_id"):
    if st.button("Upload to Google Sheets", use_container_width=True, key="gsheets_upload"):
        try:
            from gsheets import upload_daily_summary
            upload_daily_summary(filtered, sheets_config.get("spreadsheet_id", ""))
            st.success("Daily summary uploaded to Google Sheets.")
        except Exception:
            logger.exception("Google Sheets upload failed")
            st.error("Upload failed. Check logs for details.")
else:
    st.caption("Google Sheets not configured. Add `[gsheets]` section to `.streamlit/secrets.toml` to enable.")

# ------------------------------------------------------------------
# Documentation tabs
# ------------------------------------------------------------------

render_doc_tabs(DAILY_METRICS_METHODOLOGY)
