"""Tests for report_scheduler.py — scheduler job management."""

from unittest.mock import MagicMock, patch

import pytest

from auth_db import AuthDB
from report_scheduler import ReportScheduler


@pytest.fixture()
def auth_db(tmp_path):
    return AuthDB(db_path=str(tmp_path / "test_auth.db"))


@pytest.fixture()
def mock_cache():
    import pandas as pd
    cache = MagicMock()
    cache.get_orders_df.return_value = pd.DataFrame()
    cache.get_charges_df.return_value = pd.DataFrame()
    cache.get_subscriptions_df.return_value = pd.DataFrame()
    cache.get_products_df.return_value = pd.DataFrame()
    return cache


class TestReportScheduler:
    def test_start_with_no_reports(self, auth_db, mock_cache):
        scheduler = ReportScheduler(auth_db, mock_cache)
        scheduler.start()
        assert scheduler.scheduler.running
        scheduler.scheduler.shutdown(wait=False)

    def test_add_and_remove_job(self, auth_db, mock_cache):
        report = auth_db.create_scheduled_report(
            name="Test", report_type="daily_metrics",
            schedule_type="weekly", schedule_days="0,2,4",
            hour_utc=9, timezone="UTC",
            spreadsheet_id="s1", created_by="alice",
        )
        scheduler = ReportScheduler(auth_db, mock_cache)
        scheduler.start()
        assert scheduler.scheduler.get_job(f"report_{report['id']}") is not None
        scheduler.remove_report(report["id"])
        assert scheduler.scheduler.get_job(f"report_{report['id']}") is None
        scheduler.scheduler.shutdown(wait=False)

    @patch("report_scheduler.upload_report")
    @patch("report_scheduler.send_slack_dm")
    def test_execute_report_sends_dm(self, mock_dm, mock_upload, auth_db, mock_cache):
        mock_upload.return_value = "https://docs.google.com/spreadsheets/d/s1"
        mock_dm.return_value = True

        auth_db.create_user("alice", "a@x.com", "pw", "admin")
        auth_db.update_user("alice", slack_user_id="U12345ABC")

        report = auth_db.create_scheduled_report(
            name="Test", report_type="daily_metrics",
            schedule_type="weekly", schedule_days="0,1,2,3,4,5,6",
            hour_utc=9, timezone="UTC",
            spreadsheet_id="s1", created_by="alice",
        )
        scheduler = ReportScheduler(auth_db, mock_cache, slack_bot_token="xoxb-test")
        scheduler.run_now(report["id"])

        mock_upload.assert_called_once()
        mock_dm.assert_called_once_with(
            bot_token="xoxb-test",
            user_id="U12345ABC",
            report_name="Test",
            sheet_url="https://docs.google.com/spreadsheets/d/s1",
        )

    @patch("report_scheduler.upload_report")
    @patch("report_scheduler.send_slack_sheet_link")
    def test_execute_report_falls_back_to_webhook(self, mock_webhook, mock_upload, auth_db, mock_cache):
        """When no slack_user_id, falls back to webhook."""
        mock_upload.return_value = "https://docs.google.com/spreadsheets/d/s1"
        mock_webhook.return_value = True

        report = auth_db.create_scheduled_report(
            name="Test", report_type="daily_metrics",
            schedule_type="weekly", schedule_days="0,1,2,3,4,5,6",
            hour_utc=9, timezone="UTC",
            spreadsheet_id="s1", created_by="alice",
            slack_webhook="https://hooks.slack.com/xxx",
        )
        scheduler = ReportScheduler(auth_db, mock_cache)
        scheduler.run_now(report["id"])

        mock_upload.assert_called_once()
        mock_webhook.assert_called_once()

    def test_execute_inactive_report_skips(self, auth_db, mock_cache):
        report = auth_db.create_scheduled_report(
            name="Test", report_type="daily_metrics",
            schedule_type="weekly", schedule_days="0",
            hour_utc=9, timezone="UTC",
            spreadsheet_id="s1", created_by="alice",
        )
        auth_db.deactivate_scheduled_report(report["id"])
        scheduler = ReportScheduler(auth_db, mock_cache)
        scheduler.run_now(report["id"])  # should not raise
