"""Tests for video_summarizer — video ID extraction and transcript fetching."""

from unittest.mock import MagicMock, patch

import pytest

from video_summarizer import VideoTranscriptError, extract_video_id, fetch_transcript


class TestExtractVideoId:
    def test_watch_url(self):
        assert extract_video_id("https://www.youtube.com/watch?v=RQjV_y9LeU8") == "RQjV_y9LeU8"

    def test_short_url(self):
        assert extract_video_id("https://youtu.be/RQjV_y9LeU8") == "RQjV_y9LeU8"

    def test_embed_url(self):
        assert extract_video_id("https://www.youtube.com/embed/RQjV_y9LeU8") == "RQjV_y9LeU8"

    def test_live_url(self):
        assert extract_video_id("https://www.youtube.com/live/RQjV_y9LeU8") == "RQjV_y9LeU8"

    def test_watch_url_with_extra_params(self):
        assert extract_video_id("https://www.youtube.com/watch?v=RQjV_y9LeU8&t=120") == "RQjV_y9LeU8"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="IDを取得できません"):
            extract_video_id("https://www.example.com/not-youtube")

    def test_empty_url_raises(self):
        with pytest.raises(ValueError):
            extract_video_id("")


class TestFetchTranscript:
    @patch("video_summarizer.YouTubeTranscriptApi")
    def test_returns_transcript_text(self, MockApi):
        mock_entry1 = MagicMock()
        mock_entry1.text = "こんにちは"
        mock_entry2 = MagicMock()
        mock_entry2.text = "世界"

        mock_transcript = MagicMock()
        mock_transcript.fetch.return_value = [mock_entry1, mock_entry2]

        mock_list = MagicMock()
        mock_list.find_transcript.return_value = mock_transcript

        mock_api_instance = MagicMock()
        mock_api_instance.list.return_value = mock_list
        MockApi.return_value = mock_api_instance

        result = fetch_transcript("test_id")
        assert result == "こんにちは 世界"

    @patch("video_summarizer.YouTubeTranscriptApi")
    def test_raises_on_disabled_transcripts(self, MockApi):
        from youtube_transcript_api._errors import TranscriptsDisabled
        mock_api_instance = MagicMock()
        mock_api_instance.list.side_effect = TranscriptsDisabled("test_id")
        MockApi.return_value = mock_api_instance

        with pytest.raises(VideoTranscriptError, match="字幕が無効"):
            fetch_transcript("test_id")

    @patch("video_summarizer.YouTubeTranscriptApi")
    def test_raises_on_no_transcript_found(self, MockApi):
        from youtube_transcript_api._errors import NoTranscriptFound
        mock_api_instance = MagicMock()
        mock_api_instance.list.side_effect = NoTranscriptFound("test_id", [], [])
        MockApi.return_value = mock_api_instance

        with pytest.raises(VideoTranscriptError, match="字幕がありません"):
            fetch_transcript("test_id")
