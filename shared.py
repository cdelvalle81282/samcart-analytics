"""Shared singleton resources for use across app.py and all pages."""

import logging
import os

import streamlit as st

from cache import SamCartCache
from samcart_api import SamCartAPIError, SamCartClient

logger = logging.getLogger(__name__)


@st.cache_resource
def get_cache() -> SamCartCache:
    return SamCartCache()


@st.cache_resource
def get_client() -> SamCartClient:
    api_key = st.secrets.get("SAMCART_API_KEY", os.environ.get("SAMCART_API_KEY", ""))
    return SamCartClient(api_key)


def _clear_data_cache() -> None:
    """Invalidate only the data-loader caches, not auth or resource caches."""
    load_orders.clear()
    load_charges.clear()
    load_subscriptions.clear()
    load_products.clear()
    load_customers.clear()


def _run_sync(label: str, sync_fn) -> None:
    """Execute a sync function inside the sidebar with standard error handling."""
    st.session_state.sync_running = True
    try:
        with st.sidebar:
            total = sync_fn()
            st.success(f"{label} — {total:,} records")
            _clear_data_cache()
    except SamCartAPIError:
        logger.exception("SamCart API error during %s", label.lower())
        st.sidebar.error("Sync failed due to an API error.")
    except Exception:
        logger.exception("Unexpected error during %s", label.lower())
        st.sidebar.error("Sync failed unexpectedly.")
    finally:
        st.session_state.sync_running = False


def render_sync_sidebar() -> None:
    """Render sync controls and cache status in the sidebar.

    Safe to call from any page — uses the shared singleton client/cache.
    """
    client = get_client()
    cache = get_cache()

    st.sidebar.title("SamCart Analytics")

    # Credential check — cached in session_state to avoid HTTP call on every rerun
    if not client.api_key or client.api_key == "sc_live_YOUR_KEY_HERE":
        st.sidebar.error("Set your API key in `.streamlit/secrets.toml`")
    else:
        if "credentials_status" not in st.session_state:
            try:
                if client.verify_credentials():
                    st.session_state.credentials_status = "ok"
                else:
                    st.session_state.credentials_status = "invalid"
            except Exception:
                logger.exception("API key verification failed")
                st.session_state.credentials_status = "error"

        status = st.session_state.credentials_status
        if status == "ok":
            st.sidebar.success("Connected to SamCart")
        elif status == "invalid":
            st.sidebar.error("Invalid API key")
        else:
            st.sidebar.warning("Could not verify API key.")

    # Sync controls (gated by feature:sync_data permission)
    from auth import has_permission

    if has_permission("feature:sync_data"):
        st.sidebar.markdown("---")
        st.sidebar.subheader("Data Sync")

        _busy = st.session_state.get("sync_running", False)

        today_btn = st.sidebar.button(
            "Sync Today's Data",
            disabled=_busy,
            use_container_width=True,
            help="Fetches today's new orders and charges only (fast). Does not update subscription statuses or historical refunds.",
        )
        st.sidebar.caption("Captures new sales up to right now. Run anytime during the day.")

        st.sidebar.markdown("")
        force_full = st.sidebar.checkbox("Force full resync", value=False)
        full_btn = st.sidebar.button(
            "Full Sync",
            disabled=_busy,
            use_container_width=True,
            help="Full sync of all tables including subscription statuses and refunds. Runs automatically at midnight EST.",
        )

        if today_btn:
            _run_sync("Today's sync complete", lambda: cache.sync_today(client))

        if full_btn:
            _run_sync("Full sync complete", lambda: cache.sync_all(client, force_full=force_full))

    # Sync summary
    summary = cache.get_sync_summary()
    if summary:
        st.sidebar.markdown("---")
        st.sidebar.subheader("Cache Status")
        for table, meta in sorted(summary.items()):
            last = meta["last_synced_at"] or "Never"
            count = meta["record_count"] or 0
            st.sidebar.caption(f"**{table}**: {count:,} records (synced {last[:16]})")


# ------------------------------------------------------------------
# Cached data loaders — shared across all pages
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


@st.cache_data(ttl=300)
def load_products():
    return get_cache().get_products_df()


@st.cache_data(ttl=300)
def load_customers():
    return get_cache().get_customers_df()


@st.cache_resource
def get_auth_db():
    """Return the shared AuthDB instance."""
    from auth import get_auth_db as _get_auth_db
    return _get_auth_db()


@st.cache_resource
def get_scheduler():
    """Start and return the shared ReportScheduler."""
    from report_scheduler import ReportScheduler
    slack_cfg = st.secrets.get("slack", {})
    bot_token = slack_cfg.get("bot_token", "")
    scheduler = ReportScheduler(get_auth_db(), get_cache(), slack_bot_token=bot_token)
    scheduler.start()
    return scheduler


def render_doc_tabs(page_methodology: str) -> None:
    """Render standard How It's Calculated / Available Data Points tabs."""
    from methodology import API_DATA_DICTIONARY
    st.markdown("---")
    doc_tab1, doc_tab2 = st.tabs(["How It's Calculated", "Available Data Points"])
    with doc_tab1:
        st.markdown(page_methodology)
    with doc_tab2:
        st.markdown(API_DATA_DICTIONARY)
