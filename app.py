"""SamCart Analytics — navigation entry point."""

import streamlit as st

st.set_page_config(
    page_title="SamCart Analytics",
    page_icon=":bar_chart:",
    layout="wide",
)

pg = st.navigation(
    {
        "": [
            st.Page("pages/0_Overview.py", title="Overview", icon="🏠", default=True),
        ],
        "Revenue": [
            st.Page("pages/5_Revenue_Forecasting.py", title="Revenue Forecasting", icon="📈"),
            st.Page("pages/3_Product_LTV_Compare.py", title="Product LTV", icon="📦"),
            st.Page("pages/6_Refund_Analysis.py", title="Refund Analysis", icon="💸"),
            st.Page("pages/9_Product_Deep_Dive.py", title="Product Deep Dive", icon="🔍"),
        ],
        "Subscriptions": [
            st.Page("pages/2_Subscription_Cohorts.py", title="Cohorts", icon="🔁"),
            st.Page("pages/7_Subscription_Health.py", title="Health", icon="❤️"),
            st.Page("pages/4_Daily_Metrics.py", title="Daily Metrics", icon="📅"),
        ],
        "Customers": [
            st.Page("pages/1_Customer_Lookup.py", title="Customer Lookup", icon="👤"),
            st.Page("pages/8_Customer_Segments.py", title="Segments", icon="👥"),
        ],
        "Admin": [
            st.Page("pages/12_Report_Settings.py", title="Report Settings", icon="📧"),
            st.Page("pages/13_User_Management.py", title="User Management", icon="⚙️"),
            st.Page("pages/10_Audit_Log.py", title="Audit Log", icon="🔒"),
            st.Page("pages/11_PII_Approval.py", title="PII Approval", icon="🛡️"),
        ],
    }
)

pg.run()
