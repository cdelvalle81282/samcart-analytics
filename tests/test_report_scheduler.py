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
    """A mock SamCartCache that returns empty DataFrames."""
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
            name="Test", report_type="daily_metrics", frequency="daily",
            hour_utc=9, spreadsheet_id="s1", slack_webhook="w1",
            created_by="alice",
        )
        scheduler = ReportScheduler(auth_db, mock_cache)
        scheduler.start()

        assert scheduler.scheduler.get_job(f"report_{report['id']}") is not None

        scheduler.remove_report(report["id"])
        assert scheduler.scheduler.get_job(f"report_{report['id']}") is None

        scheduler.scheduler.shutdown(wait=False)

    def test_reload_report(self, auth_db, mock_cache):
        report = auth_db.create_scheduled_report(
            name="Test", report_type="daily_metrics", frequency="daily",
            hour_utc=9, spreadsheet_id="s1", slack_webhook="w1",
            created_by="alice",
        )
        scheduler = ReportScheduler(auth_db, mock_cache)
        scheduler.start()

        # Reload should update the job
        auth_db.update_scheduled_report(report["id"], hour_utc=15)
        scheduler.reload_report(report["id"])
        job = scheduler.scheduler.get_job(f"report_{report['id']}")
        assert job is not None

        scheduler.scheduler.shutdown(wait=False)

    @patch("report_scheduler.upload_report")
    @patch("report_scheduler.send_slack_sheet_link")
    def test_execute_report(self, mock_slack, mock_upload, auth_db, mock_cache):
        mock_upload.return_value = "https://docs.google.com/spreadsheets/d/s1"
        mock_slack.return_value = True

        report = auth_db.create_scheduled_report(
            name="Test", report_type="daily_metrics", frequency="daily",
            hour_utc=9, spreadsheet_id="s1", slack_webhook="w1",
            created_by="alice",
        )
        scheduler = ReportScheduler(auth_db, mock_cache)
        scheduler.run_now(report["id"])

        mock_upload.assert_called_once()
        mock_slack.assert_called_once()

    def test_execute_inactive_report_skips(self, auth_db, mock_cache):
        report = auth_db.create_scheduled_report(
            name="Test", report_type="daily_metrics", frequency="daily",
            hour_utc=9, spreadsheet_id="s1", slack_webhook="w1",
            created_by="alice",
        )
        auth_db.deactivate_scheduled_report(report["id"])

        scheduler = ReportScheduler(auth_db, mock_cache)
        # Should not raise
        scheduler.run_now(report["id"])
