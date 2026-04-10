"""Tests for site_monitor — scraping, state tracking, and update detection."""

import json
from unittest.mock import MagicMock, patch

import pytest

from site_monitor import (
    PageStructureChanged,
    check_for_updates,
    load_state,
    save_state,
    scrape_index,
)


# ---------------------------------------------------------------------------
# Sample HTML fixtures
# ---------------------------------------------------------------------------
VALID_INDEX_HTML = """
<html><body>
  <div id="__rdo_update" class="b-top">
    <p>最終更新日：2026年3月27日</p>
  </div>
  <ul class="linkE clearfix">
    <li><a href="/shingikai/meeting/005.html">2026年3月27日　第5回</a></li>
    <li><a href="/shingikai/meeting/004.html">2025年12月17日　第4回</a></li>
    <li><a href="/shingikai/meeting/003.html">2025年10月31日　第3回</a></li>
  </ul>
</body></html>
"""

MISSING_UPDATE_DIV_HTML = """
<html><body>
  <ul class="linkE clearfix">
    <li><a href="/shingikai/meeting/005.html">第5回</a></li>
  </ul>
</body></html>
"""

MISSING_LINK_LIST_HTML = """
<html><body>
  <div id="__rdo_update"><p>最終更新日：2026年3月27日</p></div>
</body></html>
"""

MISSING_BOTH_HTML = """
<html><body>
  <p>Completely redesigned page</p>
</body></html>
"""


# ---------------------------------------------------------------------------
# scrape_index
# ---------------------------------------------------------------------------
class TestScrapeIndex:
    @patch("site_monitor._get_with_retry")
    def test_extracts_date_and_links(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = VALID_INDEX_HTML
        mock_resp.apparent_encoding = "utf-8"
        mock_get.return_value = mock_resp

        result = scrape_index("https://www.meti.go.jp/shingikai/meeting/index.html")

        assert "2026年3月27日" in result["last_update_date"]
        assert len(result["links"]) == 3
        assert result["links"][0]["text"] == "2026年3月27日　第5回"
        assert result["links"][0]["href"].endswith("/005.html")

    @patch("site_monitor._get_with_retry")
    def test_raises_when_update_div_missing(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = MISSING_UPDATE_DIV_HTML
        mock_resp.apparent_encoding = "utf-8"
        mock_get.return_value = mock_resp

        with pytest.raises(PageStructureChanged, match="__rdo_update"):
            scrape_index("https://example.com/index.html")

    @patch("site_monitor._get_with_retry")
    def test_raises_when_link_list_missing(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = MISSING_LINK_LIST_HTML
        mock_resp.apparent_encoding = "utf-8"
        mock_get.return_value = mock_resp

        with pytest.raises(PageStructureChanged, match="linkE"):
            scrape_index("https://example.com/index.html")

    @patch("site_monitor._get_with_retry")
    def test_raises_with_both_warnings_when_both_missing(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = MISSING_BOTH_HTML
        mock_resp.apparent_encoding = "utf-8"
        mock_get.return_value = mock_resp

        with pytest.raises(PageStructureChanged) as exc_info:
            scrape_index("https://example.com/index.html")
        assert "__rdo_update" in str(exc_info.value)
        assert "linkE" in str(exc_info.value)

    @patch("site_monitor._get_with_retry")
    def test_resolves_relative_urls(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = VALID_INDEX_HTML
        mock_resp.apparent_encoding = "utf-8"
        mock_get.return_value = mock_resp

        result = scrape_index("https://www.meti.go.jp/shingikai/meeting/index.html")
        for link in result["links"]:
            assert link["href"].startswith("https://www.meti.go.jp")


# ---------------------------------------------------------------------------
# load_state / save_state
# ---------------------------------------------------------------------------
class TestStateIO:
    def test_load_returns_default_when_empty_db(self, tmp_path, monkeypatch):
        monkeypatch.setattr("db.DB_PATH", tmp_path / "test.db")
        state = load_state()
        assert state["last_update_date"] == ""
        assert state["known_hrefs"] == []

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("db.DB_PATH", tmp_path / "test.db")

        links = [
            {"href": "https://example.com/001.html", "text": "第1回"},
            {"href": "https://example.com/002.html", "text": "第2回"},
        ]
        save_state("2026年3月27日", links)

        state = load_state()
        assert state["last_update_date"] == "2026年3月27日"
        assert len(state["known_hrefs"]) == 2
        assert "https://example.com/001.html" in state["known_hrefs"]


# ---------------------------------------------------------------------------
# check_for_updates
# ---------------------------------------------------------------------------
class TestCheckForUpdates:
    @patch("site_monitor.load_state")
    @patch("site_monitor.scrape_index")
    def test_detects_new_links(self, mock_scrape, mock_state):
        mock_state.return_value = {
            "last_update_date": "最終更新日：2026年3月1日",
            "known_hrefs": ["https://example.com/001.html"],
            "last_checked": "",
        }
        mock_scrape.return_value = {
            "last_update_date": "最終更新日：2026年3月27日",
            "links": [
                {"href": "https://example.com/002.html", "text": "第2回"},
                {"href": "https://example.com/001.html", "text": "第1回"},
            ],
        }

        result = check_for_updates("https://example.com/index.html")

        assert result["has_update"] is True
        assert len(result["new_items"]) == 1
        assert result["new_items"][0]["href"] == "https://example.com/002.html"

    @patch("site_monitor.load_state")
    @patch("site_monitor.scrape_index")
    def test_detects_date_change_without_new_links(self, mock_scrape, mock_state):
        """A PDF swap may change the date but not add new links."""
        mock_state.return_value = {
            "last_update_date": "最終更新日：2026年3月1日",
            "known_hrefs": ["https://example.com/001.html"],
            "last_checked": "",
        }
        mock_scrape.return_value = {
            "last_update_date": "最終更新日：2026年3月27日",
            "links": [{"href": "https://example.com/001.html", "text": "第1回"}],
        }

        result = check_for_updates("https://example.com/index.html")

        assert result["has_update"] is True
        assert result["date_changed"] is True
        assert len(result["new_items"]) == 0

    @patch("site_monitor.load_state")
    @patch("site_monitor.scrape_index")
    def test_no_update_when_nothing_changed(self, mock_scrape, mock_state):
        mock_state.return_value = {
            "last_update_date": "最終更新日：2026年3月27日",
            "known_hrefs": ["https://example.com/001.html"],
            "last_checked": "",
        }
        mock_scrape.return_value = {
            "last_update_date": "最終更新日：2026年3月27日",
            "links": [{"href": "https://example.com/001.html", "text": "第1回"}],
        }

        result = check_for_updates("https://example.com/index.html")

        assert result["has_update"] is False
        assert result["new_items"] == []

    @patch("site_monitor.load_state")
    @patch("site_monitor.scrape_index")
    def test_first_run_is_not_flagged_as_date_change(self, mock_scrape, mock_state):
        """On first run (empty state), date_changed should be False."""
        mock_state.return_value = {
            "last_update_date": "",
            "known_hrefs": [],
            "last_checked": "",
        }
        mock_scrape.return_value = {
            "last_update_date": "最終更新日：2026年3月27日",
            "links": [{"href": "https://example.com/001.html", "text": "第1回"}],
        }

        result = check_for_updates("https://example.com/index.html")

        assert result["date_changed"] is False
        # But new_items should still be detected (all links are new)
        assert result["has_update"] is True
        assert len(result["new_items"]) == 1
