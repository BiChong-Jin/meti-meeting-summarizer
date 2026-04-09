"""RSS feed monitor — track new items and detect unseen entries."""

import json
from pathlib import Path

import feedparser

SEEN_FILE = Path("seen_items.json")


def _load_seen() -> set[str]:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    return set()


def _save_seen(seen: set[str]) -> None:
    SEEN_FILE.write_text(json.dumps(sorted(seen)), encoding="utf-8")


def fetch_feed(rss_url: str) -> list[dict]:
    """
    Parse the RSS/RDF feed and return all items as dicts:
    {"id": str, "title": str, "link": str, "published": str, "is_new": bool}
    """
    feed = feedparser.parse(rss_url)
    if feed.bozo and not feed.entries:
        raise ValueError(f"フィードの解析に失敗しました: {feed.bozo_exception}")

    seen = _load_seen()
    items = []
    for entry in feed.entries:
        item_id = entry.get("id") or entry.get("link", "")
        items.append(
            {
                "id": item_id,
                "title": entry.get("title", "(タイトルなし)"),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "is_new": item_id not in seen,
            }
        )
    return items


def mark_all_seen(items: list[dict]) -> None:
    """Mark all given items as seen so they won't appear as new next time."""
    seen = _load_seen()
    seen.update(item["id"] for item in items)
    _save_seen(seen)
