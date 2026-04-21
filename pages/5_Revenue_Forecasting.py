"""Report 5: Revenue Forecasting — MRR waterfall and projected revenue."""

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analytics import mrr_waterfall, revenue_forecast
from auth import require_auth, require_permission
from export import render_export_buttons
from methodology import (
    MRR_WATERFALL_METHODOLOGY,
    REVENUE_FORECAST_METHODOLOGY,
)
from automate import render_automate_button
from shared import load_subscriptions, render_doc_tabs, render_sync_sidebar


@st.cache_data(ttl=300)
def _cached_mrr_waterfall():
    return mrr_waterfall(load_subscriptions())


@st.cache_data(ttl=300)
def _cached_revenue_forecast():
    return revenue_forecast(load_subscriptions())


st.set_page_config(page_title="Revenue Forecasting", page_icon=":crystal_ball:", layout="wide")

require_auth()
require_permission("page:revenue_forecast")
render_sync_sidebar()

st.title("Revenue Forecasting")

subs_df = load_subscriptions()

if subs_df.empty:
    st.info("No subscription data yet. Run a sync from the sidebar.")
    st.stop()

# ------------------------------------------------------------------
# Tabs
# ------------------------------------------------------------------

tab1, tab2 = st.tabs(["MRR Waterfall", "Revenue Forecast"])

# --- Tab 1: MRR Waterfall ---
with tab1:
    waterfall_df = _cached_mrr_waterfall()

    if waterfall_df.empty:
        st.warning("No MRR data available.")
    else:
        # Summary metrics
        latest = waterfall_df.iloc[-1]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Latest Net MRR", f"${latest['net_mrr']:,.2f}")
        m2.metric("New MRR", f"${latest['new_mrr']:,.2f}")
        m3.metric("Churned MRR", f"${latest['churned_mrr']:,.2f}")
        m4.metric("Reactivation MRR", f"${latest['reactivation_mrr']:,.2f}")

        # Stacked bar chart
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=waterfall_df["month"], y=waterfall_df["new_mrr"],
            name="New MRR", marker_color="#2ecc71",
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
                "churned_mrr": st.column_config.NumberColumn("Churned MRR", format="$%.2f"),
                "reactivation_mrr": st.column_config.NumberColumn("Reactivation MRR", format="$%.2f"),
                "net_mrr": st.column_config.NumberColumn("Net MRR", format="$%.2f"),
            },
            use_container_width=True,
        )
        render_export_buttons(waterfall_df, "mrr_waterfall", key_prefix="mrr_wf")

    render_automate_button("mrr_waterfall", "Revenue Forecasting — MRR Waterfall", "No filters")
    st.markdown("---")
    st.markdown(MRR_WATERFALL_METHODOLOGY)

# --- Tab 2: Revenue Forecast ---
with tab2:
    forecast_df = _cached_revenue_forecast()

    if forecast_df.empty:
        st.warning("No forecast data available. Ensure subscriptions have `next_bill_date` populated (requires a full sync).")
    else:
        # Summary metrics
        m1, m2, m3 = st.columns(3)
        m1.metric("30-Day Forecast", f"${forecast_df['forecast_30d'].sum():,.2f}")
        m2.metric("60-Day Forecast", f"${forecast_df['forecast_60d'].sum():,.2f}")
        m3.metric("90-Day Forecast", f"${forecast_df['forecast_90d'].sum():,.2f}")

        # Grouped bar chart
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
    st.markdown("---")
    st.markdown(REVENUE_FORECAST_METHODOLOGY)

# ------------------------------------------------------------------
# Documentation
# ------------------------------------------------------------------

_COMBINED_METHODOLOGY = MRR_WATERFALL_METHODOLOGY + "\n\n---\n\n" + REVENUE_FORECAST_METHODOLOGY
render_doc_tabs(_COMBINED_METHODOLOGY)
