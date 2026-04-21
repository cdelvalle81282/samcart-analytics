"""Report 4: Daily Metrics — new customers, sales, refunds, renewals by product."""

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st

from analytics import (
    build_daily_summary,
    ltv_audit_charges,
    ltv_progression_by_entry_product,
    new_customer_ltv_by_entry_product,
)
from auth import require_auth, require_permission
from export import render_export_buttons
from methodology import DAILY_METRICS_METHODOLOGY
from automate import render_automate_button
from shared import load_charges, load_orders, load_subscriptions, render_doc_tabs, render_sync_sidebar

logger = logging.getLogger(__name__)

_PROGRESSION_WINDOWS = [15, 30, 60, 90, 120, 150, 180]


@st.cache_data(ttl=300)
def _cached_daily_summary():
    return build_daily_summary(load_orders(), load_charges(), load_subscriptions())


@st.cache_data(ttl=300)
def _cached_ltv_progression(ltv_start, ltv_end):
    return ltv_progression_by_entry_product(
        load_orders(), load_charges(), load_subscriptions(),
        start_date=ltv_start, end_date=ltv_end,
        windows=_PROGRESSION_WINDOWS,
    )

st.set_page_config(page_title="Daily Metrics", page_icon=":chart_with_upwards_trend:", layout="wide")

require_auth()
require_permission("page:daily_metrics")
render_sync_sidebar()

st.title("Daily Metrics")

orders_df = load_orders()
charges_df = load_charges()
subs_df = load_subscriptions()

if orders_df.empty and charges_df.empty:
    st.info("No data yet. Run a sync from the sidebar.")
    st.stop()

# ------------------------------------------------------------------
# Build summary data
# ------------------------------------------------------------------

summary_df = _cached_daily_summary()

if summary_df.empty:
    st.warning("No daily metrics data available.")
    st.stop()

# ------------------------------------------------------------------
# Filters
# ------------------------------------------------------------------

col_f1, col_f2 = st.columns(2)

products = sorted(summary_df["product_name"].dropna().unique().tolist())
selected_products = col_f1.multiselect(
    "Products",
    options=products,
    default=products,
    key="daily_product_filter",
)

min_date = summary_df["date"].min().date() if hasattr(summary_df["date"].min(), "date") else summary_df["date"].min()
today_et = datetime.now(ZoneInfo("America/New_York")).date()
data_max = summary_df["date"].max().date() if hasattr(summary_df["date"].max(), "date") else summary_df["date"].max()
max_date = min(data_max, today_et)
default_start = max(min_date, max_date - timedelta(days=30))

date_range = col_f2.date_input(
    "Date range",
    value=(default_start, max_date),
    min_value=min_date,
    max_value=max_date,
    key="daily_date_range",
)

# Apply filters
filtered = summary_df.copy()
if selected_products:
    filtered = filtered[filtered["product_name"].isin(selected_products)]
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    start, end = date_range
    filtered = filtered[
        (filtered["date"].dt.date >= start) & (filtered["date"].dt.date <= end)
    ]

if filtered.empty:
    st.warning("No data matches the selected filters.")
    st.stop()

# ------------------------------------------------------------------
# Summary metrics row
# ------------------------------------------------------------------

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total New Customers", f"{int(filtered['new_customer_count'].sum()):,}", help="Unique new-to-file customers. Each customer is counted once, attributed to the first product they purchased (by timestamp).")
m2.metric("Total New Sales", f"{int(filtered['sale_count'].sum()):,}")
m3.metric("Total Refunds", f"{int(filtered['refund_count'].sum()):,}")
m4.metric("Total Renewals", f"{int(filtered['renewal_count'].sum()):,}")

# ------------------------------------------------------------------
# Tabs
# ------------------------------------------------------------------

# Shared filter metadata for automate buttons
_products_label = ", ".join(selected_products) if selected_products else "All"
_date_label = (
    f"{date_range[0]} to {date_range[1]}"
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2
    else "All"
)
_filters_summary = f"Products: {_products_label} | {_date_label}"
_date_range_days = (
    (date_range[1] - date_range[0]).days
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2
    else 30
)
_cf = {
    "product_filter": json.dumps(selected_products) if selected_products != products else None,
    "date_range_days": _date_range_days,
}

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Daily Summary",
    "New Customers Trend",
    "New Sales Trend",
    "Refunds Trend",
    "Renewals Trend",
    "Entry Product LTV",
])

# --- Tab 1: Daily Summary Table ---
with tab1:
    display_df = filtered.copy()
    display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
    st.dataframe(
        display_df,
        column_config={
            "sale_revenue": st.column_config.NumberColumn("Sale Revenue", format="$%.2f"),
            "refund_amount": st.column_config.NumberColumn("Refund Amount", format="$%.2f"),
            "renewal_revenue": st.column_config.NumberColumn("Renewal Revenue", format="$%.2f"),
        },
        use_container_width=True,
    )
    # Export version includes totals row
    totals = {col: "" for col in display_df.columns}
    totals["date"] = "TOTAL"
    totals["product_name"] = ""
    for col in ["new_customer_count", "sale_count", "sale_revenue",
                "refund_count", "refund_amount", "renewal_count", "renewal_revenue"]:
        if col in display_df.columns:
            totals[col] = display_df[col].sum()
    export_df = pd.concat([display_df, pd.DataFrame([totals])], ignore_index=True)
    render_export_buttons(export_df, "daily_summary", key_prefix="daily_summary")
    render_automate_button("daily_metrics", "Daily Metrics — Daily Summary", _filters_summary, current_filters=_cf, key_suffix="summary")

# --- Tab 2: New Customers Trend ---
with tab2:
    daily_nc = (
        filtered.groupby(["date", "product_name"])["new_customer_count"]
        .sum()
        .reset_index()
    )
    if not daily_nc.empty:
        fig = px.line(
            daily_nc,
            x="date",
            y="new_customer_count",
            color="product_name",
            labels={"new_customer_count": "New Customers", "date": "Date", "product_name": "Product"},
            title="New Customers by Product",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No new customer data for selected filters.")
    render_automate_button("daily_metrics_new_customers", "Daily Metrics — New Customers Trend", _filters_summary, current_filters=_cf)

# --- Tab 3: New Sales Trend ---
with tab3:
    daily_ns = (
        filtered.groupby(["date", "product_name"])
        .agg(sale_count=("sale_count", "sum"), sale_revenue=("sale_revenue", "sum"))
        .reset_index()
    )
    if not daily_ns.empty:
        fig_count = px.line(
            daily_ns,
            x="date",
            y="sale_count",
            color="product_name",
            labels={"sale_count": "Sales Count", "date": "Date", "product_name": "Product"},
            title="New Sales Count by Product",
        )
        st.plotly_chart(fig_count, use_container_width=True)

        fig_rev = px.line(
            daily_ns,
            x="date",
            y="sale_revenue",
            color="product_name",
            labels={"sale_revenue": "Revenue ($)", "date": "Date", "product_name": "Product"},
            title="New Sales Revenue by Product",
        )
        fig_rev.update_layout(yaxis_tickformat="$,.0f")
        st.plotly_chart(fig_rev, use_container_width=True)
    else:
        st.info("No new sales data for selected filters.")
    render_automate_button("daily_metrics_new_sales", "Daily Metrics — New Sales Trend", _filters_summary, current_filters=_cf)

# --- Tab 4: Refunds Trend ---
with tab4:
    daily_ref = (
        filtered.groupby(["date", "product_name"])
        .agg(refund_count=("refund_count", "sum"), refund_amount=("refund_amount", "sum"))
        .reset_index()
    )
    if not daily_ref.empty:
        fig_rc = px.line(
            daily_ref,
            x="date",
            y="refund_count",
            color="product_name",
            labels={"refund_count": "Refund Count", "date": "Date", "product_name": "Product"},
            title="Refund Count by Product",
        )
        st.plotly_chart(fig_rc, use_container_width=True)

        fig_ra = px.line(
            daily_ref,
            x="date",
            y="refund_amount",
            color="product_name",
            labels={"refund_amount": "Refund Amount ($)", "date": "Date", "product_name": "Product"},
            title="Refund Amount by Product",
        )
        fig_ra.update_layout(yaxis_tickformat="$,.0f")
        st.plotly_chart(fig_ra, use_container_width=True)
    else:
        st.info("No refund data for selected filters.")
    render_automate_button("daily_metrics_refunds", "Daily Metrics — Refunds Trend", _filters_summary, current_filters=_cf)

# --- Tab 5: Renewals Trend ---
with tab5:
    daily_ren = (
        filtered.groupby(["date", "product_name"])
        .agg(renewal_count=("renewal_count", "sum"), renewal_revenue=("renewal_revenue", "sum"))
        .reset_index()
    )
    if not daily_ren.empty:
        fig_renc = px.line(
            daily_ren,
            x="date",
            y="renewal_count",
            color="product_name",
            labels={"renewal_count": "Renewal Count", "date": "Date", "product_name": "Product"},
            title="Renewal Count by Product",
        )
        st.plotly_chart(fig_renc, use_container_width=True)

        fig_renr = px.line(
            daily_ren,
            x="date",
            y="renewal_revenue",
            color="product_name",
            labels={"renewal_revenue": "Revenue ($)", "date": "Date", "product_name": "Product"},
            title="Renewal Revenue by Product",
        )
        fig_renr.update_layout(yaxis_tickformat="$,.0f")
        st.plotly_chart(fig_renr, use_container_width=True)
    else:
        st.info("No renewal data for selected filters.")
    render_automate_button("daily_metrics_renewals", "Daily Metrics — Renewals Trend", _filters_summary, current_filters=_cf)

# --- Tab 6: Entry Product LTV ---
with tab6:
    ltv_start = date_range[0] if isinstance(date_range, (list, tuple)) and len(date_range) == 2 else None
    ltv_end = date_range[1] if isinstance(date_range, (list, tuple)) and len(date_range) == 2 else None

    _CUSTOM_LABEL = "Custom..."
    _WINDOW_PRESETS: dict[str, int | None] = {"30 days": 30, "60 days": 60, "90 days": 90, "180 days": 180, "365 days": 365, "All time": None}
    _window_label = st.radio(
        "LTV window",
        options=list(_WINDOW_PRESETS.keys()) + [_CUSTOM_LABEL],
        index=2,
        horizontal=True,
        key="ltv_window_radio",
    )

    _chosen_window: int | None = None
    if _window_label == _CUSTOM_LABEL:
        _custom_days = st.number_input(
            "Days",
            min_value=1,
            max_value=3650,
            value=90,
            step=30,
            key="ltv_window_custom",
        )
        _chosen_window = int(_custom_days)
        _window_display = f"{_custom_days}-day"
    else:
        _chosen_window = _WINDOW_PRESETS[_window_label]  # type: ignore[assignment]
        _window_display = _window_label if _chosen_window is None else f"{_chosen_window}-day"

    ltv_df = new_customer_ltv_by_entry_product(
        orders_df, charges_df, subs_df,
        start_date=ltv_start, end_date=ltv_end,
        ltv_window_days=_chosen_window,
    )
    if selected_products:
        ltv_df = ltv_df[ltv_df["product_name"].isin(selected_products)]

    # Products that survived the entry price slider — used to sync the progression chart.
    # Tracked separately so prog_df is never restricted by ltv_df's maturity cutoff.
    _ep_price_products: set[str] | None = None
    if not ltv_df.empty and "avg_entry_price" in ltv_df.columns:
        _ep_min = float(ltv_df["avg_entry_price"].min())
        _ep_max = float(ltv_df["avg_entry_price"].max())
        if _ep_min < _ep_max:
            # Key includes window + products so the slider resets when the cohort changes
            _ep_key = f"ltv_entry_price_filter_{_chosen_window}_{'_'.join(sorted(selected_products or []))}"
            _ep_range = st.slider(
                "Filter by avg entry price ($)",
                min_value=_ep_min,
                max_value=_ep_max,
                value=(_ep_min, _ep_max),
                format="$%.0f",
                key=_ep_key,
            )
            ltv_df = ltv_df[
                (ltv_df["avg_entry_price"] >= _ep_range[0])
                & (ltv_df["avg_entry_price"] <= _ep_range[1])
            ]
            _ep_price_products = set(ltv_df["product_name"])

    if not ltv_df.empty:
        _chart_title = f"Average {_window_display} LTV by Entry Product"
        if _chosen_window is not None:
            st.caption(
                f"Only customers whose first purchase was at least {_chosen_window} days ago are included "
                f"(mature cohorts). Revenue counted within {_chosen_window} days of first purchase."
            )
        fig_ltv = px.bar(
            ltv_df,
            x="product_name",
            y="avg_ltv",
            text="customer_count",
            labels={"avg_ltv": f"Avg {_window_display} LTV ($)", "product_name": "Entry Product", "customer_count": "Customers"},
            title=_chart_title,
        )
        fig_ltv.update_traces(texttemplate="%{text} customers", textposition="outside")
        fig_ltv.update_layout(yaxis_tickformat="$,.0f")
        st.plotly_chart(fig_ltv, use_container_width=True)

        st.subheader("LTV Details")
        st.dataframe(
            ltv_df,
            column_config={
                "avg_entry_price": st.column_config.NumberColumn("Avg Entry Price", format="$%.2f"),
                "avg_ltv": st.column_config.NumberColumn(f"Avg {_window_display} LTV", format="$%.2f"),
                "total_ltv": st.column_config.NumberColumn("Total LTV", format="$%.2f"),
            },
            use_container_width=True,
        )
        render_export_buttons(ltv_df, "entry_product_ltv", key_prefix="entry_ltv")

        # Audit expander: consistency check + charge-level detail (computed on open only)
        with st.expander("Audit — charge-level detail"):
            _audit_raw = ltv_audit_charges(
                orders_df, charges_df, subs_df,
                start_date=ltv_start, end_date=ltv_end,
                ltv_window_days=_chosen_window,
            )
            if _audit_raw.empty:
                st.info("No charge data available for audit.")
            else:
                # Consistency check: avg_ltv should equal mean of per-customer windowed spend
                _per_cust = (
                    _audit_raw[_audit_raw["counted_in_window"]]
                    .groupby(["entry_product_name", "customer_email"])["net_amount"]
                    .sum()
                    .reset_index()
                    .groupby("entry_product_name")["net_amount"]
                    .mean()
                    .reset_index()
                    .rename(columns={"entry_product_name": "product_name", "net_amount": "computed_avg"})
                )
                _merged_check = ltv_df[["product_name", "avg_ltv"]].merge(
                    _per_cust, on="product_name", how="left"
                )
                _mismatches = _merged_check[
                    (_merged_check["computed_avg"] - _merged_check["avg_ltv"]).abs() > 0.01
                ]
                if not _mismatches.empty:
                    st.warning(
                        f"Consistency check failed for {len(_mismatches)} product(s): "
                        + ", ".join(_mismatches["product_name"].tolist())
                    )
                else:
                    st.success("Consistency check passed — all avg LTV values verified.")

                _audit_products = sorted(_audit_raw["entry_product_name"].dropna().unique().tolist())
                _audit_product_sel = st.selectbox(
                    "Entry product to inspect",
                    options=_audit_products,
                    key="ltv_audit_product",
                )
                _audit_customer_df = _audit_raw[_audit_raw["entry_product_name"] == _audit_product_sel]

                # Per-customer summary for quick scan
                _cust_summary = (
                    _audit_customer_df[_audit_customer_df["counted_in_window"]]
                    .groupby("customer_email")["net_amount"]
                    .sum()
                    .reset_index()
                    .rename(columns={"net_amount": "ltv_in_window"})
                    .sort_values("ltv_in_window", ascending=False)
                )
                st.caption(
                    f"{len(_cust_summary)} customers — avg LTV: "
                    f"${_cust_summary['ltv_in_window'].mean():.2f}"
                )
                _inspect_email = st.selectbox(
                    "Customer to inspect",
                    options=_cust_summary["customer_email"].tolist(),
                    key="ltv_audit_customer",
                )

                # Full charge history for that customer
                _cust_charges = _audit_customer_df[
                    _audit_customer_df["customer_email"] == _inspect_email
                ].copy()
                st.dataframe(
                    _cust_charges,
                    column_config={
                        "amount": st.column_config.NumberColumn("Amount", format="$%.2f"),
                        "refund_amount": st.column_config.NumberColumn("Refund", format="$%.2f"),
                        "net_amount": st.column_config.NumberColumn("Net", format="$%.2f"),
                        "counted_in_window": st.column_config.CheckboxColumn("In Window"),
                    },
                    use_container_width=True,
                )
                render_export_buttons(_audit_raw, "ltv_audit", key_prefix="ltv_audit")
    else:
        st.info(
            "No LTV data available."
            + (f" Try a smaller window — cohorts need at least {_chosen_window} days to mature." if _chosen_window else "")
        )

    st.markdown("---")
    st.subheader("LTV Progression Over Time")
    st.caption(
        "Day 1 = avg first-order spend. Subsequent windows show avg LTV at 15, 30, 60, 90, 120, 150, "
        "and 180 days after first purchase. Each window only includes customers whose cohort has fully matured."
    )
    prog_df = _cached_ltv_progression(ltv_start, ltv_end)
    if selected_products:
        prog_df = prog_df[prog_df["product_name"].isin(selected_products)]

    if _ep_price_products is not None:
        prog_df = prog_df[prog_df["product_name"].isin(_ep_price_products)]

    # avg_entry_price as Day 1 anchor; concat before the matured-cohort windows so the line starts at first-order spend
    if not ltv_df.empty and "avg_entry_price" in ltv_df.columns:
        _day1 = ltv_df[["product_name", "avg_entry_price", "customer_count"]].copy()
        _day1 = _day1.rename(columns={"avg_entry_price": "avg_ltv"})
        _day1["window_days"] = 1
        prog_df = pd.concat(
            [_day1[["window_days", "product_name", "avg_ltv", "customer_count"]], prog_df],
            ignore_index=True,
        )
        prog_df = prog_df.sort_values(["product_name", "window_days"]).reset_index(drop=True)

    _prog_tick_vals = [1] + _PROGRESSION_WINDOWS

    if not prog_df.empty:
        fig_prog = px.line(
            prog_df,
            x="window_days",
            y="avg_ltv",
            color="product_name",
            markers=True,
            labels={
                "window_days": "Days Since First Purchase",
                "avg_ltv": "Avg LTV ($)",
                "product_name": "Entry Product",
                "customer_count": "Customers",
            },
            title="Average LTV Growth by Days Since First Purchase",
            hover_data={"customer_count": True},
        )
        fig_prog.update_layout(
            xaxis=dict(tickvals=_prog_tick_vals, ticktext=["Day 1"] + [str(w) for w in _PROGRESSION_WINDOWS]),
            yaxis_tickformat="$,.0f",
        )
        st.plotly_chart(fig_prog, use_container_width=True)

        pivot = (
            prog_df.pivot_table(index="product_name", columns="window_days", values="avg_ltv", aggfunc="mean")
            .rename(columns={1: "Day 1", **{w: f"{w}d" for w in _PROGRESSION_WINDOWS}})
        )
        pivot.index.name = "Entry Product"
        st.dataframe(
            pivot.style.format("${:,.2f}", na_rep="—"),
            use_container_width=True,
        )
        render_export_buttons(prog_df, "ltv_progression", key_prefix="ltv_prog")
    else:
        st.info("Not enough mature cohort data to build a progression chart.")

    render_automate_button("daily_metrics_entry_ltv", "Daily Metrics — Entry Product LTV", _filters_summary, current_filters=_cf)

# ------------------------------------------------------------------
# Google Sheets upload
# ------------------------------------------------------------------

st.markdown("---")
st.subheader("Google Sheets Upload")

try:
    sheets_config = st.secrets.get("gsheets", None)
except Exception:
    sheets_config = None

if sheets_config and sheets_config.get("spreadsheet_id"):
    if st.button("Upload to Google Sheets", use_container_width=True, key="gsheets_upload"):
        try:
            from gsheets import upload_daily_summary
            upload_daily_summary(filtered, sheets_config.get("spreadsheet_id", ""))
            st.success("Daily summary uploaded to Google Sheets.")
        except Exception:
            logger.exception("Google Sheets upload failed")
            st.error("Upload failed. Check logs for details.")
else:
    st.caption("Google Sheets not configured. Add `[gsheets]` section to `.streamlit/secrets.toml` to enable.")

# ------------------------------------------------------------------
# Documentation tabs
# ------------------------------------------------------------------

render_doc_tabs(DAILY_METRICS_METHODOLOGY)
