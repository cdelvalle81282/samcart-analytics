"""Audit Log Viewer — admin-only page showing security and sync audit events."""

import streamlit as st

from auth import require_auth, require_permission
from shared import get_cache, render_sync_sidebar


require_auth()
require_permission("admin:audit_log")
render_sync_sidebar()

st.title("Audit Log")

cache = get_cache()

# ------------------------------------------------------------------
# Filters
# ------------------------------------------------------------------

col1, col2 = st.columns(2)
with col1:
    days = st.selectbox("Time range", [7, 14, 30, 60, 90], index=2)
with col2:
    user_filter = st.text_input("Filter by username (optional)")

df = cache.get_audit_log_df(days=days, username=user_filter or None)

# ------------------------------------------------------------------
# Results
# ------------------------------------------------------------------

if df.empty:
    st.info("No audit events found for the selected filters.")
else:
    st.dataframe(df, use_container_width=True)

    # CSV export
    csv = df.to_csv(index=False)
    st.download_button(
        "Export CSV",
        csv,
        "audit_log.csv",
        "text/csv",
        key="audit_log_export",
    )
