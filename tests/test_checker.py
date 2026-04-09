"""Tests for checker.py — main() error handling and Slack notification paths."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from site_monitor import PageStructureChanged


class TestCheckerMain:
    @patch("checker.SLACK_WEBHOOK", "https://hooks.slack.com/test")
    @patch("checker.save_state")
    @patch("checker.send_slack")
    @patch("checker.check_for_updates")
    def test_sends_slack_on_update(self, mock_check, mock_slack, mock_save):
        mock_check.return_value = {
            "has_update": True,
            "new_items": [{"href": "https://example.com/005.html", "text": "第5回"}],
            "date_changed": False,
            "last_update_date": "2026年3月27日",
            "all_links": [{"href": "https://example.com/005.html", "text": "第5回"}],
        }

        from checker import main
        main()

        mock_slack.assert_called_once()
        mock_save.assert_called_once()

    @patch("checker.SLACK_WEBHOOK", "https://hooks.slack.com/test")
    @patch("checker.save_state")
    @patch("checker.send_slack")
    @patch("checker.check_for_updates")
    def test_no_slack_when_no_update(self, mock_check, mock_slack, mock_save):
        mock_check.return_value = {
            "has_update": False,
            "new_items": [],
            "date_changed": False,
            "last_update_date": "2026年3月27日",
            "all_links": [],
        }

        from checker import main
        main()

        mock_slack.assert_not_called()
        mock_save.assert_called_once()

    @patch("checker.SLACK_WEBHOOK", "https://hooks.slack.com/test")
    @patch("checker._send_error_slack")
    @patch("checker.check_for_updates")
    def test_sends_error_slack_on_page_structure_change(self, mock_check, mock_error_slack):
        mock_check.side_effect = PageStructureChanged("linkE not found")

        from checker import main
        with pytest.raises(SystemExit):
            main()

        mock_error_slack.assert_called_once()
        assert "ページ構成" in mock_error_slack.call_args[0][0]

    @patch("checker.SLACK_WEBHOOK", "https://hooks.slack.com/test")
    @patch("checker._send_error_slack")
    @patch("checker.check_for_updates")
    def test_sends_error_slack_on_network_failure(self, mock_check, mock_error_slack):
        mock_check.side_effect = requests.ConnectionError("connection refused")

        from checker import main
        with pytest.raises(SystemExit):
            main()

        mock_error_slack.assert_called_once()
        assert "ネットワークエラー" in mock_error_slack.call_args[0][0]

    @patch("checker.SLACK_WEBHOOK", "")
    def test_exits_when_no_webhook_configured(self):
        from checker import main
        with pytest.raises(SystemExit):
            main()


class TestSendErrorSlack:
    @patch("checker.requests.post")
    @patch("checker.SLACK_WEBHOOK", "https://hooks.slack.com/test")
    def test_posts_error_to_slack(self, mock_post):
        mock_post.return_value = MagicMock()

        from checker import _send_error_slack
        _send_error_slack("test error message")

        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert "監視エラー" in payload["text"]
        assert "test error message" in payload["text"]

    @patch("checker.requests.post")
    @patch("checker.SLACK_WEBHOOK", "")
    def test_does_nothing_without_webhook(self, mock_post):
        from checker import _send_error_slack
        _send_error_slack("test error")

        mock_post.assert_not_called()
