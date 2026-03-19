"""Report 1: Customer Lookup with LTV."""

import streamlit as st

from analytics import calculate_customer_ltv
from export import render_export_buttons
from methodology import API_DATA_DICTIONARY, CUSTOMER_LOOKUP_METHODOLOGY

from shared import get_cache

st.set_page_config(page_title="Customer Lookup", page_icon=":bust_in_silhouette:", layout="wide")


st.title("Customer Lookup")

cache = get_cache()


# ------------------------------------------------------------------
# Cached data loaders
# ------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_orders():
    return get_cache().get_orders_df()


@st.cache_data(ttl=300)
def load_charges():
    return get_cache().get_charges_df()


@st.cache_data(ttl=300)
def load_subscriptions():
    return get_cache().get_subscriptions_df()


orders_df = load_orders()
charges_df = load_charges()
subs_df = load_subscriptions()

if orders_df.empty:
    st.info("No data yet. Run a sync from the sidebar.")
    st.stop()

# ------------------------------------------------------------------
# Search
# ------------------------------------------------------------------

query = st.text_input("Search by email or name", placeholder="jane@example.com")

if query:
    results = cache.search_customers(query)

    if results.empty:
        st.warning("No customers found matching that search.")
    else:
        st.subheader(f"Found {len(results)} customer(s)")
        st.dataframe(
            results[["email", "first_name", "last_name", "created_at"]],
            use_container_width=True,
        )

        # Drill into a specific customer
        emails = results["email"].tolist()
        selected_email = st.selectbox("Select a customer to view details", emails)

        if selected_email:
            st.markdown("---")
            st.subheader(f"Customer: {selected_email}")

            # Customer LTV
            ltv_df = calculate_customer_ltv(orders_df, charges_df, subs_df)
            customer_ltv = ltv_df[ltv_df["customer_email"] == selected_email]

            if not customer_ltv.empty:
                row = customer_ltv.iloc[0]
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("First Purchase", str(row.get("first_purchase", "N/A"))[:10])
                c2.metric("Total Spend", f"${row.get('total_spend', 0):,.2f}")
                c3.metric("Orders", f"{row.get('order_count', 0):,}")
                c4.metric("Active Subs", f"{row.get('active_subs', 0):,}")

            # Order history
            st.subheader("Order History")
            cust_orders = cache.get_customer_orders(selected_email)
            if not cust_orders.empty:
                st.dataframe(cust_orders, use_container_width=True)
                render_export_buttons(cust_orders, f"orders_{selected_email}", key_prefix="cust_orders")
            else:
                st.info("No orders found.")

            # Subscription history
            st.subheader("Subscriptions")
            cust_subs = cache.get_customer_subscriptions(selected_email)
            if not cust_subs.empty:
                st.dataframe(cust_subs, use_container_width=True)
            else:
                st.info("No subscriptions found.")

            # Charge history
            st.subheader("Charges")
            cust_charges = cache.get_customer_charges(selected_email)
            if not cust_charges.empty:
                st.dataframe(cust_charges, use_container_width=True)
            else:
                st.info("No charges found.")

else:
    # Show overall LTV table when no search
    st.subheader("Top Customers by LTV")
    ltv_df = calculate_customer_ltv(orders_df, charges_df, subs_df)
    if not ltv_df.empty:
        st.dataframe(ltv_df.head(50), use_container_width=True)
        render_export_buttons(ltv_df, "customer_ltv", key_prefix="all_ltv")

# ------------------------------------------------------------------
# Documentation tabs
# ------------------------------------------------------------------

st.markdown("---")
doc_tab1, doc_tab2 = st.tabs(["How It's Calculated", "Available Data Points"])
with doc_tab1:
    st.markdown(CUSTOMER_LOOKUP_METHODOLOGY)
with doc_tab2:
    st.markdown(API_DATA_DICTIONARY)
