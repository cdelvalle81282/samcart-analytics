"""Report 1: Customer Lookup with LTV."""

import logging

import streamlit as st

from analytics import calculate_customer_ltv
from auth import is_admin, require_auth, require_permission
from email_sender import get_admin_email, send_approval_email
from export import render_export_buttons
from methodology import CUSTOMER_LOOKUP_METHODOLOGY
from pii_access import check_pii_access, generate_approval_token, request_pii_access
from shared import get_cache, load_charges, load_orders, load_subscriptions, render_doc_tabs, render_sync_sidebar

logger = logging.getLogger(__name__)


@st.cache_data(ttl=300)
def _cached_ltv():
    return calculate_customer_ltv(load_orders(), load_charges(), load_subscriptions())


require_auth()
require_permission("page:customer_lookup")
render_sync_sidebar()

st.title("Customer Lookup")

# ------------------------------------------------------------------
# PII access gate — non-admins need approved PII access
# ------------------------------------------------------------------
username = st.session_state.get("username", "")

if not is_admin(username) and not check_pii_access(username):
    st.warning("This page contains personally identifiable information (PII).")
    st.info("You need PII access approval to view this page.")
    if st.button("Request PII Access"):
        try:
            rid = request_pii_access(username, "customer_lookup")
            token = generate_approval_token(rid)
            admin_email = get_admin_email()
            if admin_email:
                send_approval_email(
                    admin_email, username, "Customer Lookup", rid, token
                )
            cache = get_cache()
            cache.log_audit_event(
                username,
                "unknown",
                "pii_request",
                "customer_lookup",
                f"request_id={rid}",
                "pending",
            )
            st.success(
                "Access request sent to administrator. "
                "You'll be notified when approved."
            )
        except Exception:
            logger.exception("PII request failed")
            st.error("Failed to send request. Please try again.")
    st.stop()

if not is_admin(username):
    st.info("PII access active.")

cache = get_cache()


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
            ltv_df = _cached_ltv()
            customer_ltv = ltv_df[ltv_df["customer_email"] == selected_email]

            if not customer_ltv.empty:
                row = customer_ltv.iloc[0]
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("First Purchase", str(row.get("first_purchase", "N/A"))[:10])
                c2.metric("Total Spend", f"${row.get('total_spend', 0):,.2f}")
                c3.metric("Orders", f"{row.get('order_count', 0):,}")
                c4.metric("Active Subs", f"{row.get('active_subs', 0):,}")

            # Order history — filter in-memory, skip redundant DB round-trip
            st.subheader("Order History")
            cust_orders = orders_df[orders_df["customer_email"] == selected_email].sort_values("created_at", ascending=False)
            if not cust_orders.empty:
                st.dataframe(
                    cust_orders,
                    column_config={"total": st.column_config.NumberColumn("Total", format="$%.2f")},
                    use_container_width=True,
                )
                render_export_buttons(cust_orders, "customer_orders", key_prefix="cust_orders")
            else:
                st.info("No orders found.")

            # Subscription history
            st.subheader("Subscriptions")
            cust_subs = subs_df[subs_df["customer_email"] == selected_email].sort_values("created_at", ascending=False)
            if not cust_subs.empty:
                st.dataframe(
                    cust_subs,
                    column_config={"price": st.column_config.NumberColumn("Price", format="$%.2f")},
                    use_container_width=True,
                )
            else:
                st.info("No subscriptions found.")

            # Charge history
            st.subheader("Charges")
            cust_charges = charges_df[charges_df["customer_email"] == selected_email].sort_values("created_at", ascending=False)
            if not cust_charges.empty:
                st.dataframe(
                    cust_charges,
                    column_config={"amount": st.column_config.NumberColumn("Amount", format="$%.2f")},
                    use_container_width=True,
                )
            else:
                st.info("No charges found.")

else:
    # Show overall LTV table when no search
    st.subheader("Top Customers by LTV")
    ltv_df = _cached_ltv()
    if not ltv_df.empty:
        st.dataframe(
            ltv_df.head(50),
            column_config={
                "total_spend": st.column_config.NumberColumn("Total Spend", format="$%.2f"),
                "estimated_ltv": st.column_config.NumberColumn("Estimated LTV", format="$%.2f"),
            },
            use_container_width=True,
        )
        render_export_buttons(ltv_df, "customer_ltv", key_prefix="all_ltv")

# ------------------------------------------------------------------
# Documentation tabs
# ------------------------------------------------------------------

render_doc_tabs(CUSTOMER_LOOKUP_METHODOLOGY)
