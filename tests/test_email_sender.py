"""Tests for email_sender module with mocked SMTP."""

import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _fresh_email_module():
    """Remove email_sender from sys.modules so each test gets a fresh import."""
    sys.modules.pop("email_sender", None)
    yield
    sys.modules.pop("email_sender", None)


def _make_mock_st(with_config=True):
    """Create a mock streamlit module with email config."""
    mock_st = MagicMock()
    if with_config:
        mock_st.secrets.get.side_effect = lambda key, default=None: {
            "email": {
                "smtp_server": "smtp.test.com",
                "smtp_port": "587",
                "sender_email": "sender@test.com",
                "app_password": "test_password",
                "admin_email": "admin@test.com",
            },
            "app_base_url": "https://test.example.com",
        }.get(key, default)
    else:
        mock_st.secrets.get.side_effect = lambda key, default=None: {
            "email": {
                "smtp_server": "smtp.test.com",
                "smtp_port": "587",
                "sender_email": "",
                "app_password": "",
                "admin_email": "",
            },
            "app_base_url": "https://test.example.com",
        }.get(key, default)
    return mock_st


class TestSendApprovalEmail:
    @patch("smtplib.SMTP")
    def test_constructs_correct_html(self, mock_smtp_class):
        """send_approval_email builds HTML with approve and deny URLs."""
        mock_st = _make_mock_st()
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            sys.modules.pop("email_sender", None)
            from email_sender import send_approval_email

            result = send_approval_email(
                to_admin_email="admin@test.com",
                requester_username="alice",
                resource="customer_data",
                request_id=42,
                token="abc123token",
            )

        assert result is True

        # Verify sendmail was called
        mock_server.sendmail.assert_called_once()
        call_args = mock_server.sendmail.call_args
        from_addr = call_args[0][0]
        to_addr = call_args[0][1]
        message_body = call_args[0][2]

        assert from_addr == "sender@test.com"
        assert to_addr == "admin@test.com"

        # Check that the message contains the approve and deny URLs
        assert "action=approve" in message_body
        assert "action=deny" in message_body
        assert "rid=42" in message_body
        assert "token=abc123token" in message_body
        assert "alice" in message_body
        assert "customer_data" in message_body

    @patch("smtplib.SMTP")
    def test_uses_starttls_and_login(self, mock_smtp_class):
        """send_approval_email calls starttls and login with correct credentials."""
        mock_st = _make_mock_st()
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            sys.modules.pop("email_sender", None)
            from email_sender import send_approval_email

            send_approval_email("admin@test.com", "alice", "data", 1, "tok")

        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("sender@test.com", "test_password")

    def test_returns_false_when_not_configured(self):
        """send_approval_email returns False when email is not configured."""
        mock_st = _make_mock_st(with_config=False)

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            sys.modules.pop("email_sender", None)
            from email_sender import send_approval_email

            result = send_approval_email("admin@test.com", "alice", "data", 1, "tok")

        assert result is False

    @patch("smtplib.SMTP")
    def test_returns_false_on_smtp_error(self, mock_smtp_class):
        """send_approval_email returns False when SMTP raises an exception."""
        mock_st = _make_mock_st()
        mock_smtp_class.return_value.__enter__ = MagicMock(
            side_effect=Exception("SMTP connection failed")
        )
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            sys.modules.pop("email_sender", None)
            from email_sender import send_approval_email

            result = send_approval_email("admin@test.com", "alice", "data", 1, "tok")

        assert result is False

    @patch("smtplib.SMTP")
    def test_base_url_from_secrets(self, mock_smtp_class):
        """Approval URLs use the base URL from secrets."""
        mock_st = _make_mock_st()
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            sys.modules.pop("email_sender", None)
            from email_sender import send_approval_email

            send_approval_email("admin@test.com", "alice", "data", 1, "tok")

        message_body = mock_server.sendmail.call_args[0][2]
        assert "https://test.example.com" in message_body


class TestSendReportEmail:
    @patch("smtplib.SMTP")
    def test_sends_html_content(self, mock_smtp_class):
        """send_report_email sends the provided HTML body."""
        mock_st = _make_mock_st()
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            sys.modules.pop("email_sender", None)
            from email_sender import send_report_email

            result = send_report_email(
                to_email="manager@test.com",
                subject="Daily Report",
                html_body="<h1>Report</h1><p>All good.</p>",
            )

        assert result is True
        mock_server.sendmail.assert_called_once()
        call_args = mock_server.sendmail.call_args
        assert call_args[0][1] == "manager@test.com"
        message = call_args[0][2]
        assert "Daily Report" in message
        assert "<h1>Report</h1>" in message

    def test_returns_false_when_not_configured(self):
        """send_report_email returns False when email is not configured."""
        mock_st = _make_mock_st(with_config=False)

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            sys.modules.pop("email_sender", None)
            from email_sender import send_report_email

            result = send_report_email("a@b.com", "Subject", "<p>body</p>")

        assert result is False

    @patch("smtplib.SMTP")
    def test_returns_false_on_error(self, mock_smtp_class):
        """send_report_email returns False on SMTP error."""
        mock_st = _make_mock_st()
        mock_smtp_class.return_value.__enter__ = MagicMock(
            side_effect=Exception("Network error")
        )
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            sys.modules.pop("email_sender", None)
            from email_sender import send_report_email

            result = send_report_email("a@b.com", "Subject", "<p>body</p>")

        assert result is False
