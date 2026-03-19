"""Report 2: Subscription Cohort Retention Heatmap."""

import plotly.express as px
import streamlit as st

from analytics import build_cohort_retention
from export import render_export_buttons
from methodology import API_DATA_DICTIONARY, COHORT_RETENTION_METHODOLOGY

from shared import get_cache

st.set_page_config(page_title="Subscription Cohorts", page_icon=":chart_with_upwards_trend:", layout="wide")

st.title("Subscription Cohort Analysis")


# ------------------------------------------------------------------
# Cached data loaders
# ------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_subscriptions():
    return get_cache().get_subscriptions_df()


@st.cache_data(ttl=300)
def load_charges():
    return get_cache().get_charges_df()


@st.cache_data(ttl=300)
def load_products():
    return get_cache().get_products_df()


subs_df = load_subscriptions()
charges_df = load_charges()
products_df = load_products()

if subs_df.empty:
    st.info("No subscription data yet. Run a sync from the sidebar.")
    st.stop()

# ------------------------------------------------------------------
# Filters
# ------------------------------------------------------------------

col1, col2 = st.columns(2)

# Product filter
product_options = ["All Products"]
if not products_df.empty:
    product_options += products_df["name"].dropna().unique().tolist()
elif not subs_df.empty:
    product_options += subs_df["product_name"].dropna().unique().tolist()

selected_product = col1.selectbox("Filter by Product", product_options)

# Interval filter
interval_options = ["All Intervals"]
if not subs_df.empty:
    intervals = subs_df["interval"].dropna().unique().tolist()
    interval_options += intervals
selected_interval = col2.selectbox("Filter by Interval", interval_options)

# Apply filters
filtered_subs = subs_df.copy()
if selected_product != "All Products":
    filtered_subs = filtered_subs[filtered_subs["product_name"] == selected_product]
if selected_interval != "All Intervals":
    filtered_subs = filtered_subs[filtered_subs["interval"] == selected_interval]

if filtered_subs.empty:
    st.warning("No subscriptions match the selected filters.")
    st.stop()

# ------------------------------------------------------------------
# Summary metrics
# ------------------------------------------------------------------

total_subs = len(filtered_subs)
active = filtered_subs[filtered_subs["status"].str.lower() == "active"]
canceled = filtered_subs[filtered_subs["status"].str.lower().isin(["canceled", "cancelled"])]

c1, c2, c3 = st.columns(3)
c1.metric("Total Subscriptions", f"{total_subs:,}")
c2.metric("Currently Active", f"{len(active):,}")
churn_pct = len(canceled) / total_subs * 100 if total_subs > 0 else 0
c3.metric("Churn Rate", f"{churn_pct:.1f}%")

# ------------------------------------------------------------------
# Cohort heatmap
# ------------------------------------------------------------------

st.subheader("Retention Heatmap")
st.caption("Each cell shows the % of the cohort still active at that month")

retention = build_cohort_retention(filtered_subs, charges_df)

if retention.empty:
    st.warning("Not enough data to build cohort retention.")
    st.stop()

# Separate cohort_size from period columns for heatmap
period_cols = [c for c in retention.columns if c != "cohort_size"]
heatmap_data = retention[period_cols]

# Rename columns for display
heatmap_data.columns = [f"M{c}" for c in heatmap_data.columns]

fig = px.imshow(
    heatmap_data.values,
    labels=dict(x="Months Since Signup", y="Cohort", color="Retention %"),
    x=heatmap_data.columns.tolist(),
    y=heatmap_data.index.tolist(),
    color_continuous_scale="RdYlGn",
    zmin=0,
    zmax=100,
    text_auto=".0f",
    aspect="auto",
)
fig.update_layout(height=max(400, len(heatmap_data) * 30))
st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------
# Table view toggle
# ------------------------------------------------------------------

if st.checkbox("Show raw retention table"):
    display_df = retention.copy()
    display_df.insert(0, "Cohort Size", display_df.pop("cohort_size"))
    st.dataframe(display_df, use_container_width=True)
    render_export_buttons(display_df.reset_index(), "cohort_retention", key_prefix="cohort")

# ------------------------------------------------------------------
# Documentation tabs
# ------------------------------------------------------------------

st.markdown("---")
doc_tab1, doc_tab2 = st.tabs(["How It's Calculated", "Available Data Points"])
with doc_tab1:
    st.markdown(COHORT_RETENTION_METHODOLOGY)
with doc_tab2:
    st.markdown(API_DATA_DICTIONARY)
