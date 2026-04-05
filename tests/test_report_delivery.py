"""Tests for report delivery — gsheets upload_report + Slack sheet link."""

from unittest.mock import MagicMock, patch


from notifications import send_slack_sheet_link


class TestSendSlackSheetLink:
    @patch("notifications.requests.post")
    def test_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        result = send_slack_sheet_link(
            "https://hooks.slack.com/xxx",
            "Weekly Revenue",
            "https://docs.google.com/spreadsheets/d/abc123",
        )
        assert result is True
        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert payload["blocks"][0]["text"]["text"] == "Report: Weekly Revenue"

    @patch("notifications.requests.post")
    def test_failure(self, mock_post):
        mock_post.side_effect = Exception("Connection error")
        result = send_slack_sheet_link(
            "https://hooks.slack.com/xxx",
            "Weekly Revenue",
            "https://docs.google.com/spreadsheets/d/abc123",
        )
        assert result is False
