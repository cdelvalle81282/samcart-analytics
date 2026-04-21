"""Report 9: Product Deep Dive — MRR trend, attach rate, revenue mix."""

import json

import plotly.express as px
import streamlit as st

from analytics import (
    new_vs_renewal_revenue_mix,
    product_attach_rate,
    product_mrr_trend,
)
from auth import require_auth, require_permission
from export import render_export_buttons
from methodology import (
    ATTACH_RATE_METHODOLOGY,
    PRODUCT_MRR_TREND_METHODOLOGY,
    REVENUE_MIX_METHODOLOGY,
)
from automate import render_automate_button
from shared import load_charges, load_orders, load_subscriptions, render_doc_tabs, render_sync_sidebar


@st.cache_data(ttl=300)
def _cached_product_mrr_trend():
    return product_mrr_trend(load_subscriptions())


@st.cache_data(ttl=300)
def _cached_product_attach_rate():
    return product_attach_rate(load_orders())


@st.cache_data(ttl=300)
def _cached_revenue_mix():
    return new_vs_renewal_revenue_mix(load_charges(), load_orders(), load_subscriptions())


st.set_page_config(page_title="Product Deep Dive", page_icon=":package:", layout="wide")

require_auth()
require_permission("page:product_deep_dive")
render_sync_sidebar()

st.title("Product Deep Dive")

subs_df = load_subscriptions()
orders_df = load_orders()
charges_df = load_charges()

if subs_df.empty and orders_df.empty and charges_df.empty:
    st.info("No data yet. Run a sync from the sidebar.")
    st.stop()

# ------------------------------------------------------------------
# Tabs
# ------------------------------------------------------------------

tab1, tab2, tab3 = st.tabs(["MRR Trend", "Attach Rate", "Revenue Mix"])

# --- Tab 1: Product MRR Trend ---
with tab1:
    mrr_df = _cached_product_mrr_trend()

    if mrr_df.empty:
        st.warning("No MRR trend data available.")
    else:
        fig = px.line(
            mrr_df,
            x="month",
            y="mrr",
            color="product_name",
            labels={"mrr": "MRR ($)", "month": "Month", "product_name": "Product"},
            title="Monthly MRR by Product",
            markers=True,
        )
        fig.update_layout(yaxis_tickformat="$,.0f")
        st.plotly_chart(fig, use_container_width=True)

        # Product filter for detail view
        products = sorted(mrr_df["product_name"].unique().tolist())
        selected = st.selectbox("Select product for detail", products, key="mrr_trend_product")
        detail = mrr_df[mrr_df["product_name"] == selected]
        st.dataframe(
            detail,
            column_config={"mrr": st.column_config.NumberColumn("MRR", format="$%.2f")},
            use_container_width=True,
        )
        render_export_buttons(mrr_df, "product_mrr_trend", key_prefix="mrr_trend")

    render_automate_button("product_deep_dive", "Product Deep Dive — MRR Trend", "No filters", key_suffix="mrr")
    st.markdown("---")
    st.markdown(PRODUCT_MRR_TREND_METHODOLOGY)

# --- Tab 2: Attach Rate ---
with tab2:
    attach_df = _cached_product_attach_rate()

    if attach_df.empty:
        st.warning("Not enough product diversity for attach rate analysis (need at least 2 products with 5+ buyers each).")
    else:
        # Heatmap
        products = sorted(set(attach_df["product_a"]) | set(attach_df["product_b"]))
        if len(products) <= 20:
            pivot = attach_df.pivot_table(
                index="product_a", columns="product_b", values="attach_rate_pct", fill_value=0
            )
            fig = px.imshow(
                pivot,
                labels={"x": "Product B", "y": "Product A", "color": "Attach Rate (%)"},
                title="Cross-Sell Attach Rate Heatmap",
                color_continuous_scale="YlOrRd",
            )
            st.plotly_chart(fig, use_container_width=True)

        # Select a product for bar view
        product_options = sorted(attach_df["product_a"].unique().tolist())
        selected_product = st.selectbox("Show attach rates from:", product_options, key="attach_from")

        product_attach = attach_df[attach_df["product_a"] == selected_product].sort_values("attach_rate_pct", ascending=True)
        if not product_attach.empty:
            fig_bar = px.bar(
                product_attach,
                x="attach_rate_pct",
                y="product_b",
                orientation="h",
                labels={"attach_rate_pct": "Attach Rate (%)", "product_b": "Product"},
                title=f"Attach Rate from {selected_product}",
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        st.dataframe(
            attach_df,
            column_config={
                "attach_rate_pct": st.column_config.NumberColumn("Attach Rate (%)", format="%.2f%%"),
            },
            use_container_width=True,
        )
        render_export_buttons(attach_df, "product_attach_rate", key_prefix="attach")

    render_automate_button("product_deep_dive_attach", "Product Deep Dive — Attach Rate", "No filters")
    st.markdown("---")
    st.markdown(ATTACH_RATE_METHODOLOGY)

# --- Tab 3: Revenue Mix ---
with tab3:
    mix_df = _cached_revenue_mix()

    # Initialize so the automate button below always has a value
    _mix_all_products: list[str] = []
    selected_products: list[str] = []

    if mix_df.empty:
        st.warning("No revenue mix data available.")
    else:
        # Product filter
        _mix_all_products = sorted(mix_df["product_name"].dropna().unique().tolist())
        selected_products = st.multiselect(
            "Products",
            options=_mix_all_products,
            default=_mix_all_products,
            key="mix_product_filter",
        )
        filtered = mix_df[mix_df["product_name"].isin(selected_products)] if selected_products else mix_df

        if not filtered.empty:
            # Stacked bar chart
            fig = px.bar(
                filtered,
                x="month",
                y=["new_revenue", "renewal_revenue"],
                color_discrete_map={"new_revenue": "#3498db", "renewal_revenue": "#2ecc71"},
                barmode="stack",
                labels={"value": "Revenue ($)", "month": "Month", "variable": "Type"},
                title="New vs Renewal Revenue",
                facet_col="product_name" if len(selected_products) <= 4 else None,
            )
            fig.update_layout(yaxis_tickformat="$,.0f")
            st.plotly_chart(fig, use_container_width=True)

            st.dataframe(
                filtered,
                column_config={
                    "new_revenue": st.column_config.NumberColumn("New Revenue", format="$%.2f"),
                    "renewal_revenue": st.column_config.NumberColumn("Renewal Revenue", format="$%.2f"),
                    "total_revenue": st.column_config.NumberColumn("Total Revenue", format="$%.2f"),
                    "new_pct": st.column_config.NumberColumn("New %", format="%.1f%%"),
                    "renewal_pct": st.column_config.NumberColumn("Renewal %", format="%.1f%%"),
                },
                use_container_width=True,
            )
            render_export_buttons(filtered, "revenue_mix", key_prefix="rev_mix")
        else:
            st.info("No data matches the selected products.")

    # Only pass product_filter when it's a real subset; "all products" → None
    # so the scheduled report picks up future products automatically.
    _mix_is_subset = selected_products and selected_products != _mix_all_products
    _mix_products_label = ", ".join(selected_products) if _mix_is_subset else "All"
    render_automate_button(
        "product_deep_dive_revenue_mix",
        "Product Deep Dive — Revenue Mix",
        f"Products: {_mix_products_label}",
        current_filters={"product_filter": json.dumps(selected_products) if _mix_is_subset else None},
    )
    st.markdown("---")
    st.markdown(REVENUE_MIX_METHODOLOGY)

# ------------------------------------------------------------------
# Documentation
# ------------------------------------------------------------------

_COMBINED_METHODOLOGY = (
    PRODUCT_MRR_TREND_METHODOLOGY
    + "\n\n---\n\n"
    + ATTACH_RATE_METHODOLOGY
    + "\n\n---\n\n"
    + REVENUE_MIX_METHODOLOGY
)
render_doc_tabs(_COMBINED_METHODOLOGY)
