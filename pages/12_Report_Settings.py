"""Admin-only page for viewing and testing report configurations."""

import logging

import streamlit as st

from analytics import build_daily_summary
from auth import require_admin, require_auth
from notifications import (
    ManagerConfig,
    NotificationChannel,
    NotificationFrequency,
    dispatch_notifications,
)
from shared import get_cache, render_sync_sidebar

logger = logging.getLogger(__name__)


require_auth()
require_admin()
render_sync_sidebar()

st.title("Report Settings")

# ------------------------------------------------------------------
# Load config
# ------------------------------------------------------------------

reports_cfg = st.secrets.get("reports", [])

if not reports_cfg:
    st.info(
        "No reports configured. Add `[[reports]]` entries to secrets.toml."
    )
    st.stop()

st.subheader("Configured Reports")

for i, report in enumerate(reports_cfg):
    name = report.get("name", "Unnamed Report")
    frequency = report.get("frequency", "daily")
    channel = report.get("channel", "email")
    destination = report.get("destination", "")
    products = report.get("products", [])

    with st.expander(f"{name} ({channel} / {frequency})", expanded=False):
        st.write(f"**Channel:** {channel}")
        st.write(f"**Frequency:** {frequency}")
        st.write(
            f"**Destination:** {destination or '(default webhook)'}"
        )
        st.write(
            f"**Products:** {', '.join(products) if products else 'All'}"
        )

        if st.button("Send Test Report", key=f"test_report_{i}"):
            with st.spinner("Sending test report..."):
                try:
                    cache = get_cache()
                    orders_df = cache.get_orders_df()
                    charges_df = cache.get_charges_df()
                    subs_df = cache.get_subscriptions_df()
                    summary_df = build_daily_summary(
                        orders_df, charges_df, subs_df
                    )

                    mgr = ManagerConfig(
                        name=name,
                        channel=NotificationChannel(channel),
                        frequency=NotificationFrequency(frequency),
                        destination=destination,
                        products=products,
                    )
                    results = dispatch_notifications(summary_df, [mgr])
                    if results.get(name):
                        st.success("Test report sent successfully!")
                    else:
                        st.error(
                            "Failed to send test report. Check logs."
                        )
                except Exception:
                    logger.exception(
                        "Test report failed for %s", name
                    )
                    st.error(
                        "Failed to send test report. "
                        "Check logs for details."
                    )
