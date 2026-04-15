"""Scrape PDF links from a web page and download them into memory."""

import logging
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

PDF_MAGIC = b"%PDF"
MAX_RETRIES = 3


class ScraperWarning(Exception):
    """Non-fatal issue the caller should surface to the user."""


def _get_with_retry(url: str, timeout: int = 10) -> requests.Response:
    """GET with simple retry for transient network errors."""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.ConnectionError as e:
            last_err = e
            log.warning("Attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, url, e)
        except requests.Timeout as e:
            last_err = e
            log.warning("Attempt %d/%d timed out for %s", attempt, MAX_RETRIES, url)
    raise requests.ConnectionError(
        f"{MAX_RETRIES}回リトライしましたが接続できませんでした: {last_err}"
    )


_YT_PATTERN = re.compile(
    r"https?://(?:(?:www\.)?youtube\.com/(?:watch\?v=|embed/|live/)|youtu\.be/)[A-Za-z0-9_-]{11}"
)


def _parse_pdf_links(soup: BeautifulSoup, page_url: str) -> list[dict]:
    seen: set[str] = set()
    results = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.lower().endswith(".pdf"):
            continue
        full_url = urljoin(page_url, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        path = urlparse(full_url).path
        filename = path.split("/")[-1] or "document.pdf"
        link_text = a.get_text(strip=True)
        if link_text:
            safe_text = "".join(c if c.isalnum() or c in "-_ " else "_" for c in link_text)
            filename = f"{safe_text[:60].strip()}_{filename}"
        results.append({"filename": filename, "url": full_url})
    return results


def _normalize_yt_url(url: str) -> str:
    """Ensure URL has https:// prefix, keep original format (live/embed/watch)."""
    url = re.sub(r"youtu\.be/([A-Za-z0-9_-]{11})", r"youtube.com/watch?v=\1", url)
    if url.startswith("youtube.com"):
        url = "https://www." + url
    return url


def _parse_video_links(soup: BeautifulSoup, page_url: str) -> list[dict]:
    seen: set[str] = set()
    results = []

    # 1. <a href> tags
    for a in soup.find_all("a", href=True):
        full_url = urljoin(page_url, a["href"])
        if _YT_PATTERN.search(full_url) and full_url not in seen:
            seen.add(full_url)
            results.append({"title": a.get_text(strip=True) or full_url, "url": _normalize_yt_url(full_url)})

    # 2. <iframe src> tags (embedded players)
    for iframe in soup.find_all("iframe", src=True):
        full_url = urljoin(page_url, iframe["src"])
        if _YT_PATTERN.search(full_url) and full_url not in seen:
            seen.add(full_url)
            results.append({"title": iframe.get("title", "") or full_url, "url": _normalize_yt_url(full_url)})

    # 3. Fallback: raw HTML regex scan (catches JS-embedded URLs)
    for match in _YT_PATTERN.finditer(str(soup)):
        url = match.group(0)
        normalized = _normalize_yt_url(url)
        if normalized not in seen:
            seen.add(normalized)
            results.append({"title": normalized, "url": normalized})

    return results


def _parse_meeting_meta(soup: BeautifulSoup) -> dict:
    """Extract meeting title and date from the page."""
    title_tag = soup.find("h1", id="MainContentsArea")
    title = title_tag.get_text(strip=True) if title_tag else ""

    date = ""
    for h2 in soup.find_all("h2"):
        if "開催日" in h2.get_text():
            p = h2.find_next_sibling("p")
            if p:
                date = p.get_text(strip=True)
            break

    return {"title": title, "date": date}


def scrape_page(page_url: str) -> dict:
    """
    Fetch a meeting page once and return everything:
      - title: str
      - date: str
      - pdf_links: list[{"filename", "url"}]
      - video_links: list[{"title", "url"}]

    Raises ScraperWarning if no PDF links are found.
    """
    resp = _get_with_retry(page_url)
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "html.parser")

    pdf_links = _parse_pdf_links(soup, page_url)
    if not pdf_links:
        log.warning("No PDF links found on %s — page structure may have changed", page_url)
        raise ScraperWarning(
            "PDFリンクが見つかりませんでした。ページ構成が変更された可能性があります。URLを確認してください。"
        )

    return {
        **_parse_meeting_meta(soup),
        "pdf_links": pdf_links,
        "video_links": _parse_video_links(soup, page_url),
    }


def download_pdf(url: str) -> bytes:
    """Download a single PDF and return its raw bytes.
    Raises ValueError if the response doesn't look like a PDF."""
    resp = _get_with_retry(url, timeout=60)
    data = resp.content

    if data[:4] != PDF_MAGIC:
        raise ValueError(
            f"ダウンロードしたファイルがPDF形式ではありません（HTMLエラーページの可能性）: {url}"
        )

    return data
