"""Admin page: User Management, Permissions, and Scheduled Reports."""

import datetime
import json
import logging
from zoneinfo import ZoneInfo

import streamlit as st

from auth import get_auth_db, require_auth, require_permission
from auth_db import ALL_PERMISSIONS, ROLE_DEFAULTS
from report_catalog import REPORT_CATALOG
from shared import get_scheduler, render_sync_sidebar

logger = logging.getLogger(__name__)

COMMON_TIMEZONES = [
    "America/Los_Angeles",
    "America/Denver",
    "America/Chicago",
    "America/New_York",
    "UTC",
]

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _format_schedule(report: dict) -> str:
    """Format schedule for display in the report's timezone."""
    tz_name = report.get("timezone", "America/Los_Angeles")
    try:
        tz = ZoneInfo(tz_name)
    except KeyError:
        tz = ZoneInfo("America/Los_Angeles")

    # Prefer hour_local (stable across DST) when available; fall back to
    # reverse-converting hour_utc for legacy records that predate this field.
    if report.get("hour_local") is not None:
        local_time = datetime.time(report["hour_local"], report.get("minute_local") or 0)
        ref_dt = datetime.datetime.combine(datetime.date.today(), local_time, tzinfo=tz)
        tz_abbr = ref_dt.strftime("%Z")
    else:
        utc_time = datetime.time(report["hour_utc"], report.get("minute_utc") or 0)
        utc_dt = datetime.datetime.combine(
            datetime.date.today(), utc_time, tzinfo=ZoneInfo("UTC")
        )
        local_dt = utc_dt.astimezone(tz)
        local_time = local_dt.time()
        tz_abbr = local_dt.strftime("%Z")

    local_time = datetime.time.strftime(local_time, "%I:%M %p").lstrip("0")

    schedule_type = report.get("schedule_type", "weekly")
    if schedule_type == "monthly":
        dom = report.get("day_of_month", 1)
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(
            dom if dom < 20 else dom % 10, "th"
        )
        if 11 <= dom <= 13:
            suffix = "th"
        return f"Monthly on the {dom}{suffix} at {local_time} {tz_abbr}"

    schedule_days = report.get("schedule_days", "0,1,2,3,4,5,6")
    if schedule_days:
        day_indices = sorted(
            int(d.strip()) for d in schedule_days.split(",") if d.strip()
        )
        day_names = [DAY_NAMES[d] for d in day_indices if d < 7]
        if len(day_names) == 7:
            return f"Every day at {local_time} {tz_abbr}"
        return f"{', '.join(day_names)} at {local_time} {tz_abbr}"
    return f"Every day at {local_time} {tz_abbr}"



require_auth()
require_permission("admin:manage_users")
render_sync_sidebar()

st.title("User Management")

auth_db = get_auth_db()
current_user = st.session_state.get("username", "")
current_role = st.session_state.get("user_role", "viewer")

tab_users, tab_perms, tab_reports = st.tabs(
    ["Users", "Permissions", "Scheduled Reports"]
)

# ══════════════════════════════════════════════════════════════════════════════
# Tab 1 — Users
# ══════════════════════════════════════════════════════════════════════════════

with tab_users:
    st.subheader("All Users")

    users = auth_db.list_users()
    if users:
        for user in users:
            status = "Active" if user["is_active"] else "Inactive"
            with st.expander(
                f"{user['username']} — {user['role']} ({status})", expanded=False
            ):
                st.write(f"**Email:** {user['email']}")
                st.write(f"**Role:** {user['role']}")
                st.write(f"**Status:** {status}")
                st.write(f"**Created by:** {user['created_by'] or 'system'}")
                st.write(f"**Created at:** {user['created_at']}")

                col1, col2, col3 = st.columns(3)

                # Deactivate / Reactivate
                if user["username"] != current_user:
                    if user["is_active"]:
                        if col1.button(
                            "Deactivate",
                            key=f"deact_{user['username']}",
                        ):
                            try:
                                auth_db.deactivate_user(user["username"])
                                st.success(f"Deactivated {user['username']}")
                                st.rerun()
                            except ValueError as e:
                                st.error(str(e))
                    else:
                        if col1.button(
                            "Reactivate",
                            key=f"react_{user['username']}",
                        ):
                            auth_db.reactivate_user(user["username"])
                            st.success(f"Reactivated {user['username']}")
                            st.rerun()

                # Reset Password
                with col2.popover("Reset Password"):
                    new_pw = st.text_input(
                        "New password",
                        type="password",
                        key=f"pw_{user['username']}",
                    )
                    if st.button("Confirm Reset", key=f"pw_btn_{user['username']}"):
                        if new_pw and len(new_pw) >= 8:
                            auth_db.reset_password(user["username"], new_pw)
                            st.success("Password reset.")
                        else:
                            st.error("Password must be at least 8 characters.")

                # Change Role
                allowed_roles = (
                    ["super_admin", "admin", "viewer"]
                    if current_role == "super_admin"
                    else ["admin", "viewer"]
                )
                if user["username"] != current_user:
                    new_role = col3.selectbox(
                        "Role",
                        allowed_roles,
                        index=allowed_roles.index(user["role"])
                        if user["role"] in allowed_roles
                        else 0,
                        key=f"role_{user['username']}",
                    )
                    if new_role != user["role"]:
                        if col3.button(
                            "Update Role",
                            key=f"role_btn_{user['username']}",
                        ):
                            auth_db.update_user(user["username"], role=new_role)
                            st.success(
                                f"Updated {user['username']} to {new_role}"
                            )
                            st.rerun()

                # Slack User ID
                slack_row = auth_db.conn.execute(
                    "SELECT slack_user_id FROM users WHERE username = ?",
                    (user["username"],),
                ).fetchone()
                current_slack_id = (
                    (slack_row["slack_user_id"] or "") if slack_row else ""
                )

                new_slack_id = st.text_input(
                    "Slack User ID",
                    value=current_slack_id,
                    key=f"slack_{user['username']}",
                    help="Find in Slack: Profile > \u22ee > Copy member ID",
                )
                if new_slack_id != current_slack_id:
                    if st.button(
                        "Update Slack ID",
                        key=f"slack_btn_{user['username']}",
                    ):
                        auth_db.update_user(
                            user["username"],
                            slack_user_id=new_slack_id or None,
                        )
                        st.success("Slack ID updated.")
                        st.rerun()

    st.markdown("---")
    st.subheader("Add User")

    with st.form("add_user_form"):
        new_username = st.text_input("Username")
        new_email = st.text_input("Email")
        new_password = st.text_input("Temporary Password", type="password")
        role_options = (
            ["viewer", "admin", "super_admin"]
            if current_role == "super_admin"
            else ["viewer", "admin"]
        )
        new_role = st.selectbox("Role", role_options)
        submitted = st.form_submit_button("Create User")

        if submitted:
            if not new_username or not new_email or not new_password:
                st.error("All fields are required.")
            elif len(new_password) < 8:
                st.error("Password must be at least 8 characters.")
            else:
                try:
                    auth_db.create_user(
                        new_username, new_email, new_password,
                        new_role, created_by=current_user,
                    )
                    st.success(f"Created user: {new_username}")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


# ══════════════════════════════════════════════════════════════════════════════
# Tab 2 — Permissions
# ══════════════════════════════════════════════════════════════════════════════

with tab_perms:
    st.subheader("User Permissions")

    usernames = [u["username"] for u in auth_db.list_users()]
    if not usernames:
        st.info("No users found.")
    else:
        selected_user = st.selectbox("Select user", usernames, key="perm_user")
        user_info = auth_db.get_user(selected_user)

        if user_info:
            st.write(f"**Role:** {user_info['role']}")
            role_defaults = ROLE_DEFAULTS.get(user_info["role"], set())
            overrides = auth_db.get_permission_overrides(selected_user)
            effective = auth_db.get_permissions(selected_user)

            st.markdown("---")

            # Group permissions by category
            categories: dict[str, list[str]] = {}
            for perm in ALL_PERMISSIONS:
                cat = perm.split(":")[0]
                categories.setdefault(cat, []).append(perm)

            for cat, perms in sorted(categories.items()):
                st.markdown(f"**{cat.title()}**")
                for perm in perms:
                    is_default = perm in role_defaults
                    is_granted = perm in effective
                    is_override = perm in overrides

                    label = perm
                    if is_override:
                        label += " (custom override)"

                    new_val = st.checkbox(
                        label, value=is_granted,
                        key=f"perm_{selected_user}_{perm}",
                    )

                    # Only save if changed from effective state
                    if new_val != is_granted:
                        auth_db.set_permission(selected_user, perm, new_val)
                        st.rerun()

            st.markdown("---")
            if st.button("Reset to Role Defaults", key="reset_perms"):
                auth_db.reset_permissions_to_defaults(selected_user)
                st.success(f"Permissions reset for {selected_user}")
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# Tab 3 — Scheduled Reports
# ══════════════════════════════════════════════════════════════════════════════

with tab_reports:
    st.subheader("Scheduled Reports")

    reports = auth_db.list_scheduled_reports()
    if reports:
        for report in reports:
            status = "Active" if report["is_active"] else "Inactive"
            schedule_label = _format_schedule(report)
            with st.expander(
                f"{report['name']} — {schedule_label} ({status})",
                expanded=False,
            ):
                st.write(f"**Type:** {report['report_type']}")
                st.write(f"**Schedule:** {schedule_label}")
                if report.get("product_filter"):
                    st.write(f"**Product filter:** {report['product_filter']}")
                st.write(
                    f"**Date range:** {report.get('date_range_days', 30)} days"
                )
                if report.get("extra_params"):
                    try:
                        ep = json.loads(report["extra_params"])
                        st.write(f"**Extra filters:** {', '.join(f'{k}: {v}' for k, v in ep.items())}")
                    except (json.JSONDecodeError, TypeError):
                        pass
                st.write(f"**Created by:** {report['created_by']}")

                col1, col2 = st.columns(2)
                if report["is_active"]:
                    if col1.button(
                        "Deactivate", key=f"rpt_deact_{report['id']}"
                    ):
                        auth_db.deactivate_scheduled_report(report["id"])
                        try:
                            get_scheduler().remove_report(report["id"])
                        except Exception:
                            pass
                        st.success(f"Deactivated: {report['name']}")
                        st.rerun()

                if col2.button("Send Now", key=f"rpt_send_{report['id']}"):
                    with st.spinner("Running report..."):
                        try:
                            get_scheduler().run_now(report["id"])
                            st.success(f"Report sent: {report['name']}")
                        except Exception:
                            logger.exception(
                                "Send Now failed for %s", report["name"]
                            )
                            st.error("Failed to send report. Check logs.")

    st.markdown("---")
    st.subheader("Add Scheduled Report")

    with st.form("add_report_form"):
        rpt_name = st.text_input("Report Name")
        rpt_type = st.selectbox(
            "Report Type",
            list(REPORT_CATALOG.keys()),
            format_func=lambda k: REPORT_CATALOG[k]["name"],
        )

        rpt_schedule_type = st.radio(
            "Schedule", ["Weekly", "Monthly"], horizontal=True
        )

        selected_days: list[int] = []
        rpt_dom = 1
        if rpt_schedule_type == "Weekly":
            st.caption("Select which days to receive the report:")
            day_cols = st.columns(7)
            for i, (col, name) in enumerate(zip(day_cols, DAY_NAMES)):
                if col.checkbox(name, value=i < 5, key=f"day_{i}"):
                    selected_days.append(i)
        else:
            rpt_dom = st.number_input(
                "Day of month", min_value=1, max_value=28, value=1
            )

        rpt_tz = st.selectbox("Timezone", COMMON_TIMEZONES, index=0)
        rpt_time = st.time_input("Delivery time", value=datetime.time(7, 0))

        rpt_range = st.number_input("Date range (days)", min_value=1, value=30)
        rpt_product = st.text_input(
            "Product filter (comma-separated, blank=all)"
        )
        rpt_sheet = st.text_input("Google Spreadsheet ID")

        rpt_submitted = st.form_submit_button("Create Report")

        if rpt_submitted:
            if not rpt_name or not rpt_sheet:
                st.error("Name and Spreadsheet ID are required.")
            elif rpt_schedule_type == "Weekly" and not selected_days:
                st.error("Select at least one day.")
            else:
                # Store local hour+minute for DST-aware scheduling; also keep
                # UTC equivalents for backward-compat.
                hour_local = rpt_time.hour
                minute_local = rpt_time.minute
                local_tz = ZoneInfo(rpt_tz)
                local_dt = datetime.datetime.combine(
                    datetime.date.today(),
                    rpt_time,
                    tzinfo=local_tz,
                )
                utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
                hour_utc = utc_dt.hour
                minute_utc = utc_dt.minute

                try:
                    report = auth_db.create_scheduled_report(
                        name=rpt_name,
                        report_type=rpt_type,
                        schedule_type=rpt_schedule_type.lower(),
                        schedule_days=(
                            ",".join(str(d) for d in selected_days)
                            if rpt_schedule_type == "Weekly"
                            else None
                        ),
                        day_of_month=(
                            int(rpt_dom)
                            if rpt_schedule_type == "Monthly"
                            else None
                        ),
                        hour_utc=hour_utc,
                        hour_local=hour_local,
                        minute_utc=minute_utc,
                        minute_local=minute_local,
                        timezone=rpt_tz,
                        spreadsheet_id=rpt_sheet,
                        created_by=current_user,
                        product_filter=rpt_product or None,
                        date_range_days=int(rpt_range),
                    )
                    try:
                        get_scheduler().reload_report(report["id"])
                    except Exception:
                        pass
                    st.success(f"Created report: {rpt_name}")
                    st.rerun()
                except Exception:
                    logger.exception("Failed to create report")
                    st.error("Failed to create report. Check logs.")
