"""Tests for pdf_fetcher — retry logic, PDF link extraction, and download validation."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from pdf_fetcher import (
    ScraperWarning,
    _get_with_retry,
    download_pdf,
    scrape_page,
)


# ---------------------------------------------------------------------------
# _get_with_retry
# ---------------------------------------------------------------------------
class TestGetWithRetry:
    @patch("pdf_fetcher.requests.get")
    def test_success_on_first_attempt(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = _get_with_retry("https://example.com")
        assert result is mock_resp
        assert mock_get.call_count == 1

    @patch("pdf_fetcher.requests.get")
    def test_retries_on_connection_error_then_succeeds(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_get.side_effect = [
            requests.ConnectionError("fail 1"),
            mock_resp,
        ]

        result = _get_with_retry("https://example.com")
        assert result is mock_resp
        assert mock_get.call_count == 2

    @patch("pdf_fetcher.requests.get")
    def test_retries_on_timeout_then_succeeds(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_get.side_effect = [
            requests.Timeout("timeout 1"),
            requests.Timeout("timeout 2"),
            mock_resp,
        ]

        result = _get_with_retry("https://example.com")
        assert result is mock_resp
        assert mock_get.call_count == 3

    @patch("pdf_fetcher.requests.get")
    def test_raises_after_max_retries(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("always fails")

        with pytest.raises(requests.ConnectionError, match="3回リトライ"):
            _get_with_retry("https://example.com")
        assert mock_get.call_count == 3

    @patch("pdf_fetcher.requests.get")
    def test_http_error_not_retried(self, mock_get):
        """Non-transient HTTP errors (e.g. 404) should raise immediately via raise_for_status."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404")
        mock_get.return_value = mock_resp

        with pytest.raises(requests.HTTPError):
            _get_with_retry("https://example.com")
        assert mock_get.call_count == 1


# ---------------------------------------------------------------------------
# scrape_page — PDF link extraction
# ---------------------------------------------------------------------------
SAMPLE_HTML_WITH_PDFS = """
<html><body>
  <h1 id="MainContentsArea">第5回 テスト会議</h1>
  <div class="main w1000"><h2>開催日</h2><p>2026年3月27日</p></div>
  <a href="/docs/report.pdf">レポート資料</a>
  <a href="./appendix.pdf">参考資料</a>
  <a href="/other/page.html">議事録</a>
</body></html>
"""

SAMPLE_HTML_NO_PDFS = """
<html><body>
  <a href="/other/page.html">議事録</a>
  <p>No PDF links here</p>
</body></html>
"""

SAMPLE_HTML_DUPLICATE_PDFS = """
<html><body>
  <a href="/docs/report.pdf">レポート資料</a>
  <a href="/docs/report.pdf">レポート資料（重複）</a>
  <a href="/docs/other.pdf">その他</a>
</body></html>
"""


class TestScrapePage:
    @patch("pdf_fetcher._get_with_retry")
    def test_extracts_pdf_links(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_HTML_WITH_PDFS
        mock_resp.apparent_encoding = "utf-8"
        mock_get.return_value = mock_resp

        result = scrape_page("https://example.com/meeting/005.html")
        links = result["pdf_links"]

        assert len(links) == 2
        assert links[0]["url"] == "https://example.com/docs/report.pdf"
        assert links[1]["url"] == "https://example.com/meeting/appendix.pdf"
        assert "レポート資料" in links[0]["filename"]

    @patch("pdf_fetcher._get_with_retry")
    def test_extracts_title_and_date(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_HTML_WITH_PDFS
        mock_resp.apparent_encoding = "utf-8"
        mock_get.return_value = mock_resp

        result = scrape_page("https://example.com/meeting/005.html")
        assert result["title"] == "第5回 テスト会議"
        assert result["date"] == "2026年3月27日"

    @patch("pdf_fetcher._get_with_retry")
    def test_raises_scraper_warning_when_no_pdfs(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_HTML_NO_PDFS
        mock_resp.apparent_encoding = "utf-8"
        mock_get.return_value = mock_resp

        with pytest.raises(ScraperWarning, match="PDFリンクが見つかりませんでした"):
            scrape_page("https://example.com/empty.html")

    @patch("pdf_fetcher._get_with_retry")
    def test_deduplicates_pdf_links(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_HTML_DUPLICATE_PDFS
        mock_resp.apparent_encoding = "utf-8"
        mock_get.return_value = mock_resp

        result = scrape_page("https://example.com/page.html")
        urls = [l["url"] for l in result["pdf_links"]]

        assert len(urls) == 2
        assert urls.count("https://example.com/docs/report.pdf") == 1


# ---------------------------------------------------------------------------
# download_pdf
# ---------------------------------------------------------------------------
class TestDownloadPdf:
    @patch("pdf_fetcher._get_with_retry")
    def test_returns_valid_pdf_bytes(self, mock_get):
        pdf_content = b"%PDF-1.4 fake pdf content..."
        mock_resp = MagicMock()
        mock_resp.content = pdf_content
        mock_get.return_value = mock_resp

        result = download_pdf("https://example.com/doc.pdf")
        assert result == pdf_content

    @patch("pdf_fetcher._get_with_retry")
    def test_raises_on_html_error_page(self, mock_get):
        html_content = b"<html><body>404 Not Found</body></html>"
        mock_resp = MagicMock()
        mock_resp.content = html_content
        mock_get.return_value = mock_resp

        with pytest.raises(ValueError, match="PDF形式ではありません"):
            download_pdf("https://example.com/doc.pdf")

    @patch("pdf_fetcher._get_with_retry")
    def test_raises_on_empty_response(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.content = b""
        mock_get.return_value = mock_resp

        with pytest.raises(ValueError, match="PDF形式ではありません"):
            download_pdf("https://example.com/doc.pdf")
