"""Reusable "Schedule This Report" component for all analytics pages."""

from __future__ import annotations

import datetime
import json
from zoneinfo import ZoneInfo

import streamlit as st

from auth import get_auth_db, has_permission
from shared import get_scheduler

_COMMON_TIMEZONES = [
    "America/Los_Angeles",
    "America/Denver",
    "America/Chicago",
    "America/New_York",
    "UTC",
]

_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def render_automate_button(
    report_type: str,
    default_name: str,
    filters_summary: str,
    current_filters: dict | None = None,
    extra_params: dict | None = None,
    key_suffix: str = "",
) -> None:
    """Render a collapsed expander with a schedule-report form.

    Args:
        report_type: Key in REPORT_CATALOG (e.g. "daily_metrics").
        default_name: Pre-filled report name shown in the form.
        filters_summary: Human-readable filter description shown as a caption.
        current_filters: Dict with optional keys:
            - "product_filter": comma-separated product names (str | None)
            - "date_range_days": int
        extra_params: Extra kwargs to pass to the generator at run time
            (e.g. {"interval_filter": "monthly", "product_id": "123"}).
        key_suffix: Appended to all widget keys to prevent collisions when the
            same report_type appears in multiple tabs on one page.
    """
    if not has_permission("feature:schedule_reports"):
        return

    cf = current_filters or {}
    ep = extra_params or {}
    _key = f"{report_type}_{key_suffix}"

    with st.expander("Schedule This Report", expanded=False):
        st.caption(f"Current view: {filters_summary}")

        # Schedule type radio OUTSIDE the form so it can gate form contents
        schedule_type = st.radio(
            "Schedule",
            ["Weekly", "Monthly"],
            horizontal=True,
            key=f"automate_sched_type_{_key}",
        )

        with st.form(key=f"automate_form_{_key}"):
            report_name = st.text_input(
                "Report Name",
                value=default_name,
                key=f"automate_name_{_key}",
            )

            if schedule_type == "Weekly":
                st.caption("Deliver on:")
                day_cols = st.columns(7)
                selected_days: list[int] = []
                for i, (col, day_name) in enumerate(zip(day_cols, _DAY_NAMES)):
                    # Default: Mon–Fri checked
                    if col.checkbox(day_name, value=i < 5, key=f"automate_day_{i}_{_key}"):
                        selected_days.append(i)
                dom = None
            else:
                selected_days = []
                dom = st.number_input(
                    "Day of month",
                    min_value=1,
                    max_value=28,
                    value=1,
                    key=f"automate_dom_{_key}",
                )

            tz_name = st.selectbox(
                "Timezone",
                _COMMON_TIMEZONES,
                index=0,
                key=f"automate_tz_{_key}",
            )

            delivery_time = st.time_input(
                "Delivery time",
                value=datetime.time(7, 0),
                key=f"automate_time_{_key}",
            )

            spreadsheet_id = st.text_input(
                "Google Spreadsheet ID",
                help="The ID from your Google Sheets URL (between /d/ and /edit)",
                key=f"automate_sheet_{_key}",
            )

            submitted = st.form_submit_button("Schedule Report")

        if submitted:
            errors = []
            if not report_name.strip():
                errors.append("Report name is required.")
            if not spreadsheet_id.strip():
                errors.append("Spreadsheet ID is required.")
            if schedule_type == "Weekly" and not selected_days:
                errors.append("Select at least one day.")

            if errors:
                for err in errors:
                    st.error(err)
                return

            # Store local hour+minute for DST-aware scheduling; also store UTC
            # equivalents for backward-compat.
            local_tz = ZoneInfo(tz_name)
            hour_local = delivery_time.hour
            minute_local = delivery_time.minute
            local_dt = datetime.datetime.combine(
                datetime.date.today(), delivery_time, tzinfo=local_tz
            )
            utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
            hour_utc = utc_dt.hour
            minute_utc = utc_dt.minute

            schedule_days_str = (
                ",".join(str(d) for d in selected_days)
                if schedule_type == "Weekly"
                else None
            )

            extra_params_json = json.dumps(ep) if ep else None
            product_filter_str = cf.get("product_filter") or None
            date_range_days = int(cf.get("date_range_days", 30))
            username = st.session_state.get("username", "")

            try:
                auth_db = get_auth_db()
                report = auth_db.create_scheduled_report(
                    name=report_name.strip(),
                    report_type=report_type,
                    schedule_type=schedule_type.lower(),
                    schedule_days=schedule_days_str,
                    day_of_month=int(dom) if dom is not None else None,
                    hour_utc=hour_utc,
                    hour_local=hour_local,
                    minute_utc=minute_utc,
                    minute_local=minute_local,
                    timezone=tz_name,
                    spreadsheet_id=spreadsheet_id.strip(),
                    created_by=username,
                    product_filter=product_filter_str,
                    date_range_days=date_range_days,
                    extra_params=extra_params_json,
                )
                try:
                    get_scheduler().reload_report(report["id"])
                except Exception:
                    pass  # Scheduler may not be running in all envs
                st.success(
                    f"'{report_name.strip()}' scheduled. "
                    "Manage it in **User Management → Scheduled Reports**."
                )
            except Exception as exc:
                st.error(f"Failed to create report: {exc}")
