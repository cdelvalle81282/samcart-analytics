"""Tests for report delivery — gsheets upload_report + Slack sheet link."""

from unittest.mock import MagicMock, patch


from notifications import send_slack_dm, send_slack_sheet_link


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


class TestSendSlackDM:
    @patch("notifications.requests.post")
    def test_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.json.return_value = {"ok": True}
        mock_post.return_value.raise_for_status = MagicMock()
        result = send_slack_dm(
            bot_token="xoxb-test-token",
            user_id="U12345ABC",
            report_name="Weekly Revenue",
            sheet_url="https://docs.google.com/spreadsheets/d/abc123",
        )
        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["headers"]["Authorization"] == "Bearer xoxb-test-token"
        payload = call_kwargs[1]["json"]
        assert payload["channel"] == "U12345ABC"

    @patch("notifications.requests.post")
    def test_failure(self, mock_post):
        mock_post.side_effect = Exception("Connection error")
        result = send_slack_dm(
            bot_token="xoxb-test-token",
            user_id="U12345ABC",
            report_name="Test",
            sheet_url="https://example.com",
        )
        assert result is False

    def test_missing_bot_token(self):
        result = send_slack_dm(
            bot_token="",
            user_id="U12345ABC",
            report_name="Test",
            sheet_url="https://example.com",
        )
        assert result is False

    def test_missing_user_id(self):
        result = send_slack_dm(
            bot_token="xoxb-test-token",
            user_id="",
            report_name="Test",
            sheet_url="https://example.com",
        )
        assert result is False
