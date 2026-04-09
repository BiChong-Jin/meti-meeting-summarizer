"""Scrape a METI committee index page and detect new meeting entries."""

import json
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from pdf_fetcher import _get_with_retry

log = logging.getLogger(__name__)

STATE_FILE = Path("monitor_state.json")


class PageStructureChanged(Exception):
    """Raised when expected HTML elements are missing from the page."""


def scrape_index(index_url: str) -> dict:
    """
    Fetch the committee index page and extract:
      - last_update_date: text from <div id="__rdo_update">
      - links: list of {href, text} from <ul class="linkE clearfix">

    Raises PageStructureChanged if key elements are not found.
    """
    from bs4 import BeautifulSoup

    resp = _get_with_retry(index_url)
    resp.encoding = resp.apparent_encoding

    soup = BeautifulSoup(resp.text, "html.parser")

    warnings = []

    # Last updated date
    update_div = soup.find("div", id="__rdo_update")
    if not update_div:
        warnings.append("更新日（id='__rdo_update'）が見つかりません")
        log.warning("__rdo_update div not found on %s", index_url)
    last_update = update_div.get_text(strip=True) if update_div else ""

    # Meeting link list
    link_ul = soup.find("ul", class_="linkE")
    if not link_ul:
        warnings.append("会議リスト（class='linkE'）が見つかりません")
        log.warning("linkE ul not found on %s", index_url)

    links = []
    if link_ul:
        for a in link_ul.find_all("a", href=True):
            full_href = urljoin(index_url, a["href"])
            links.append({"href": full_href, "text": a.get_text(strip=True)})

    if warnings:
        raise PageStructureChanged(
            "ページ構成が変更された可能性があります:\n・" + "\n・".join(warnings)
        )

    return {"last_update_date": last_update, "links": links}


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"last_update_date": "", "known_hrefs": [], "last_checked": ""}


def save_state(last_update_date: str, links: list[dict]) -> None:
    state = {
        "last_update_date": last_update_date,
        "known_hrefs": [l["href"] for l in links],
        "last_checked": datetime.now().isoformat(timespec="seconds"),
    }
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def check_for_updates(index_url: str) -> dict:
    """
    Scrape the index page and compare with stored state.
    Returns:
      {
        "has_update": bool,
        "new_items": [{"href": ..., "text": ...}],
        "last_update_date": str,
        "last_checked": str,
      }
    """
    scraped = scrape_index(index_url)
    state = load_state()

    known_hrefs = set(state["known_hrefs"])
    new_items = [l for l in scraped["links"] if l["href"] not in known_hrefs]

    # Also flag if update date changed but no new links detected (e.g. PDF swap)
    date_changed = (
        state["last_update_date"] != scraped["last_update_date"]
        and state["last_update_date"] != ""
    )
    has_update = bool(new_items) or date_changed

    return {
        "has_update": has_update,
        "new_items": new_items,
        "date_changed": date_changed,
        "last_update_date": scraped["last_update_date"],
        "all_links": scraped["links"],
    }
