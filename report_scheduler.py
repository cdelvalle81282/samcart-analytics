"""APScheduler-based report scheduler — runs as background thread in Streamlit."""

from __future__ import annotations

import datetime
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from auth_db import AuthDB
from cache import SamCartCache
from gsheets import upload_report
from notifications import send_slack_dm, send_slack_sheet_link
from report_catalog import REPORT_CATALOG, generate_report

logger = logging.getLogger(__name__)


class ReportScheduler:
    """Manages scheduled report jobs backed by auth_db."""

    def __init__(self, auth_db: AuthDB, cache: SamCartCache, slack_bot_token: str = ""):
        self.auth_db = auth_db
        self.cache = cache
        self.slack_bot_token = slack_bot_token
        self.scheduler = BackgroundScheduler()

    def start(self) -> None:
        """Load all active reports from DB and start the scheduler."""
        reports = self.auth_db.list_scheduled_reports(active_only=True)
        for report in reports:
            self._add_job(report)
        self.scheduler.start()

    def _add_job(self, report: dict) -> None:
        """Register an APScheduler job for a scheduled report."""
        trigger = self._build_trigger(report)
        self.scheduler.add_job(
            self._execute_report,
            trigger=trigger,
            args=[report["id"]],
            id=f"report_{report['id']}",
            replace_existing=True,
        )

    def _build_trigger(self, report: dict) -> CronTrigger:
        """Build a CronTrigger from report config."""
        schedule_type = report.get("schedule_type") or report.get("frequency", "weekly")
        if schedule_type == "monthly":
            return CronTrigger(hour=report["hour_utc"], day=report.get("day_of_month", 1))
        # Weekly: fire daily at hour_utc, job checks schedule_days at execution time
        return CronTrigger(hour=report["hour_utc"])

    def _execute_report(self, report_id: int) -> None:
        """Run a single report: generate -> upload -> notify."""
        report = self.auth_db.get_scheduled_report(report_id)
        if not report or not report["is_active"]:
            return

        # Day-of-week check for weekly reports
        schedule_type = report.get("schedule_type") or report.get("frequency", "weekly")
        if schedule_type == "weekly":
            schedule_days = report.get("schedule_days", "0,1,2,3,4,5,6")
            if schedule_days:
                today_weekday = datetime.datetime.now(tz=datetime.timezone.utc).weekday()
                allowed_days = [int(d.strip()) for d in schedule_days.split(",") if d.strip()]
                if today_weekday not in allowed_days:
                    return

        if report["report_type"] not in REPORT_CATALOG:
            logger.error("Unknown report type: %s", report["report_type"])
            return

        product_filter = (
            report["product_filter"].split(",")
            if report.get("product_filter")
            else None
        )

        try:
            df = generate_report(
                report["report_type"],
                self.cache,
                date_range_days=report.get("date_range_days", 30),
                product_filter=product_filter,
            )
            sheet_url = upload_report(df, report["spreadsheet_id"], report["name"])

            # Try Slack DM first, fall back to webhook
            delivered = False
            if self.slack_bot_token and report.get("created_by"):
                creator = self.auth_db.get_user(report["created_by"])
                if creator and creator.get("slack_user_id"):
                    delivered = send_slack_dm(
                        bot_token=self.slack_bot_token,
                        user_id=creator["slack_user_id"],
                        report_name=report["name"],
                        sheet_url=sheet_url,
                    )

            if not delivered and report.get("slack_webhook"):
                send_slack_sheet_link(report["slack_webhook"], report["name"], sheet_url)

            logger.info("Report delivered: %s", report["name"])
        except Exception:
            logger.exception("Failed to execute report: %s", report["name"])

    def reload_report(self, report_id: int) -> None:
        """Reload a single report job (called after admin edits)."""
        job_id = f"report_{report_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
        report = self.auth_db.get_scheduled_report(report_id)
        if report and report["is_active"]:
            self._add_job(report)

    def remove_report(self, report_id: int) -> None:
        """Remove a report job."""
        job_id = f"report_{report_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

    def run_now(self, report_id: int) -> None:
        """Immediately execute a report (for test/preview)."""
        self._execute_report(report_id)
