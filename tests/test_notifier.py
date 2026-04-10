"""Tests for notifier — Slack webhook message formatting and sending."""

from unittest.mock import MagicMock, patch

import pytest

from notifier import send_slack


class TestSendSlack:
    @patch("notifier.requests.post")
    def test_sends_message_with_new_items(self, mock_post):
        mock_post.return_value = MagicMock()
        result = {
            "last_update_date": "最終更新日：2026年3月27日",
            "new_items": [
                {"href": "https://example.com/005.html", "text": "第5回"},
            ],
            "date_changed": False,
        }
        send_slack("https://hooks.slack.com/test", "https://example.com", result)

        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert "新着情報" in payload["text"]
        assert "第5回" in payload["text"]

    @patch("notifier.requests.post")
    def test_sends_message_for_date_change_only(self, mock_post):
        mock_post.return_value = MagicMock()
        result = {
            "last_update_date": "最終更新日：2026年3月27日",
            "new_items": [],
            "date_changed": True,
        }
        send_slack("https://hooks.slack.com/test", "https://example.com", result)

        payload = mock_post.call_args[1]["json"]
        assert "更新日が変わっています" in payload["text"]

    @patch("notifier.requests.post")
    def test_includes_index_url(self, mock_post):
        mock_post.return_value = MagicMock()
        result = {
            "last_update_date": "2026年3月27日",
            "new_items": [{"href": "https://example.com/005.html", "text": "第5回"}],
            "date_changed": False,
        }
        send_slack("https://hooks.slack.com/test", "https://example.com/index.html", result)

        payload = mock_post.call_args[1]["json"]
        assert "example.com/index.html" in payload["text"]

    @patch("notifier.requests.post")
    def test_raises_on_http_error(self, mock_post):
        import requests
        mock_post.return_value = MagicMock()
        mock_post.return_value.raise_for_status.side_effect = requests.HTTPError("500")

        result = {
            "last_update_date": "2026年3月27日",
            "new_items": [],
            "date_changed": False,
        }
        with pytest.raises(requests.HTTPError):
            send_slack("https://hooks.slack.com/test", "https://example.com", result)
