"""Fetch a YouTube transcript and summarize it using the LLM."""

import logging
import re

from youtube_transcript_api import YouTubeTranscriptApi

log = logging.getLogger(__name__)
from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled


class VideoTranscriptError(Exception):
    """Raised when the transcript cannot be retrieved."""


def extract_video_id(url: str) -> str:
    """Extract the YouTube video ID from a URL.
    Supports formats:
      - https://www.youtube.com/watch?v=VIDEO_ID
      - https://youtu.be/VIDEO_ID
      - https://www.youtube.com/embed/VIDEO_ID
    """
    patterns = [
        r"(?:v=)([A-Za-z0-9_-]{11})",
        r"(?:youtu\.be/)([A-Za-z0-9_-]{11})",
        r"(?:embed/)([A-Za-z0-9_-]{11})",
        r"(?:live/)([A-Za-z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"YouTube動画のIDを取得できませんでした: {url}")


def fetch_transcript(video_id: str) -> str:
    """Fetch the transcript for a YouTube video.
    Tries Japanese first, then falls back to English or any available language.
    Raises VideoTranscriptError if no transcript is available.
    """
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)

        # Try Japanese first, then English, then any available language
        for fetch_method in [
            lambda: transcript_list.find_transcript(["ja"]),
            lambda: transcript_list.find_transcript(["en"]),
            lambda: transcript_list.find_manually_created_transcript(),
            lambda: transcript_list.find_generated_transcript(["ja", "en"]),
        ]:
            try:
                fetched = fetch_method().fetch()
                log.info("Transcript fetched for %s (%d entries)", video_id, len(fetched))
                return " ".join(entry.text for entry in fetched)
            except Exception as e:
                log.debug("Transcript method failed for %s: %s", video_id, e)
                continue

        raise VideoTranscriptError("利用可能な字幕が見つかりませんでした。")

    except TranscriptsDisabled:
        raise VideoTranscriptError("この動画は字幕が無効になっています。")
    except NoTranscriptFound:
        raise VideoTranscriptError("この動画に字幕がありません。")
