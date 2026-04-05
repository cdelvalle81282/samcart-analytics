"""Report 8: Customer Segments — RFM, multi-product buyers, concentration."""

import plotly.express as px
import streamlit as st

from analytics import customer_concentration, multi_product_buyers, rfm_segmentation
from auth import require_auth, require_permission
from export import render_export_buttons
from methodology import (
    CONCENTRATION_METHODOLOGY,
    MULTI_PRODUCT_METHODOLOGY,
    RFM_METHODOLOGY,
)
from shared import load_charges, load_orders, render_doc_tabs, render_sync_sidebar

st.set_page_config(page_title="Customer Segments", page_icon=":busts_in_silhouette:", layout="wide")

require_auth()
require_permission("page:customer_segments")
render_sync_sidebar()

st.title("Customer Segments")

orders_df = load_orders()
charges_df = load_charges()

if orders_df.empty and charges_df.empty:
    st.info("No data yet. Run a sync from the sidebar.")
    st.stop()

# ------------------------------------------------------------------
# Tabs
# ------------------------------------------------------------------

tab1, tab2, tab3 = st.tabs(["RFM Segmentation", "Multi-Product Buyers", "Revenue Concentration"])

# --- Tab 1: RFM Segmentation ---
with tab1:
    rfm_df = rfm_segmentation(orders_df, charges_df)

    if rfm_df.empty:
        st.warning("Not enough customers for RFM analysis (need at least 10).")
    else:
        # Segment summary
        segment_counts = rfm_df["segment"].value_counts().reset_index()
        segment_counts.columns = ["segment", "count"]

        m1, m2 = st.columns(2)
        with m1:
            fig_seg = px.bar(
                segment_counts.sort_values("count"),
                x="count",
                y="segment",
                orientation="h",
                labels={"count": "Customers", "segment": "Segment"},
                title="Customers by Segment",
                color="segment",
            )
            st.plotly_chart(fig_seg, use_container_width=True)

        with m2:
            fig_scatter = px.scatter(
                rfm_df,
                x="recency_days",
                y="frequency",
                size="monetary",
                color="segment",
                labels={
                    "recency_days": "Recency (days)",
                    "frequency": "Frequency (orders)",
                    "monetary": "Monetary ($)",
                    "segment": "Segment",
                },
                title="RFM Scatter (size = monetary)",
                hover_data=["customer_email"],
            )
            st.plotly_chart(fig_scatter, use_container_width=True)

        # Filter by segment
        selected_segment = st.selectbox(
            "Filter by segment",
            options=["All"] + sorted(rfm_df["segment"].unique().tolist()),
            key="rfm_segment_filter",
        )
        display_rfm = rfm_df if selected_segment == "All" else rfm_df[rfm_df["segment"] == selected_segment]

        st.dataframe(
            display_rfm,
            column_config={
                "monetary": st.column_config.NumberColumn("Monetary", format="$%.2f"),
            },
            use_container_width=True,
        )
        render_export_buttons(display_rfm, "rfm_segments", key_prefix="rfm")

    st.markdown("---")
    st.markdown(RFM_METHODOLOGY)

# --- Tab 2: Multi-Product Buyers ---
with tab2:
    buyer_summary, product_combos = multi_product_buyers(orders_df)

    if buyer_summary.empty:
        st.warning("No multi-product buyers found.")
    else:
        m1, m2 = st.columns(2)
        m1.metric("Multi-Product Buyers", f"{len(buyer_summary):,}")
        m2.metric("Avg Products per Multi-Buyer", f"{buyer_summary['product_count'].mean():.1f}")

        st.subheader("Buyer Summary")
        st.dataframe(buyer_summary, use_container_width=True)
        render_export_buttons(buyer_summary, "multi_product_buyers", key_prefix="mpb")

    if not product_combos.empty:
        st.subheader("Product Pair Frequency")

        # Heatmap
        products = sorted(set(product_combos["product_a"]) | set(product_combos["product_b"]))
        if len(products) <= 20:
            pivot = product_combos.pivot_table(
                index="product_a", columns="product_b", values="pair_count", fill_value=0
            )
            fig_hm = px.imshow(
                pivot,
                labels={"x": "Product B", "y": "Product A", "color": "Customers"},
                title="Product Pair Heatmap",
                color_continuous_scale="Blues",
            )
            st.plotly_chart(fig_hm, use_container_width=True)

        st.dataframe(product_combos, use_container_width=True)

    st.markdown("---")
    st.markdown(MULTI_PRODUCT_METHODOLOGY)

# --- Tab 3: Revenue Concentration ---
with tab3:
    conc_df = customer_concentration(charges_df)

    if conc_df.empty:
        st.warning("No revenue concentration data available.")
    else:
        # Key metrics
        total_customers = len(conc_df)
        m1, m2, m3 = st.columns(3)

        top10_pct = conc_df.loc[conc_df["rank"] <= 10, "cumulative_pct"].max() if total_customers >= 10 else 0
        top50_pct = conc_df.loc[conc_df["rank"] <= 50, "cumulative_pct"].max() if total_customers >= 50 else 0
        top100_pct = conc_df.loc[conc_df["rank"] <= 100, "cumulative_pct"].max() if total_customers >= 100 else 0

        m1.metric("Top 10 Customers", f"{top10_pct:.1f}% of revenue")
        m2.metric("Top 50 Customers", f"{top50_pct:.1f}% of revenue")
        m3.metric("Top 100 Customers", f"{top100_pct:.1f}% of revenue")

        # Pareto chart
        display_limit = min(100, total_customers)
        pareto = conc_df.head(display_limit).copy()

        fig = px.bar(
            pareto,
            x="rank",
            y="total_revenue",
            labels={"rank": "Customer Rank", "total_revenue": "Revenue ($)"},
            title=f"Revenue Concentration (Top {display_limit})",
        )
        fig.add_scatter(
            x=pareto["rank"], y=pareto["cumulative_pct"],
            name="Cumulative %", yaxis="y2",
            mode="lines", line={"color": "red", "width": 2},
        )
        fig.update_layout(
            yaxis_tickformat="$,.0f",
            yaxis2={
                "title": "Cumulative %",
                "overlaying": "y",
                "side": "right",
                "range": [0, 105],
            },
        )
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Customer Revenue Ranking")
        st.dataframe(
            conc_df.head(200),
            column_config={
                "total_revenue": st.column_config.NumberColumn("Revenue", format="$%.2f"),
                "cumulative_revenue": st.column_config.NumberColumn("Cumulative Revenue", format="$%.2f"),
                "cumulative_pct": st.column_config.NumberColumn("Cumulative %", format="%.2f%%"),
            },
            use_container_width=True,
        )
        render_export_buttons(conc_df, "customer_concentration", key_prefix="conc")

    st.markdown("---")
    st.markdown(CONCENTRATION_METHODOLOGY)

# ------------------------------------------------------------------
# Documentation
# ------------------------------------------------------------------

_COMBINED_METHODOLOGY = (
    RFM_METHODOLOGY
    + "\n\n---\n\n"
    + MULTI_PRODUCT_METHODOLOGY
    + "\n\n---\n\n"
    + CONCENTRATION_METHODOLOGY
)
render_doc_tabs(_COMBINED_METHODOLOGY)
