"""Shared report storage — save and load generated reports for all users."""

import json
import time
import uuid
from pathlib import Path

REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(exist_ok=True)


def save_report(
    title: str,
    date: str,
    content: str,
    sources: list[str],
    source_type: str = "pdf",  # "pdf" or "video"
) -> str:
    """Save a report and return its ID."""
    report_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    data = {
        "id": report_id,
        "title": title or "(タイトルなし)",
        "date": date or "",
        "content": content,
        "sources": sources,
        "source_type": source_type,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    path = REPORTS_DIR / f"{report_id}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_id


def _all_reports_meta(source_type: str | None = None) -> list[dict]:
    """Load all report metadata, optionally filtered by source_type."""
    reports = []
    for f in REPORTS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if source_type and data.get("source_type") != source_type:
                continue
            reports.append({k: v for k, v in data.items() if k != "content"})
        except Exception:
            continue
    return sorted(reports, key=lambda r: r.get("date", "") or r.get("created_at", ""), reverse=True)


def list_reports() -> list[dict]:
    """Return PDF report metadata sorted by meeting date newest-first."""
    return _all_reports_meta(source_type="pdf")


def list_video_reports() -> list[dict]:
    """Return video report metadata sorted by meeting date newest-first."""
    return _all_reports_meta(source_type="video")


def _search(query: str, source_type: str) -> list[dict]:
    query_lower = query.lower()
    results = []
    for f in REPORTS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("source_type") != source_type:
                continue
            searchable = " ".join([
                data.get("title", ""),
                data.get("date", ""),
                data.get("content", ""),
                " ".join(data.get("sources", [])),
            ]).lower()
            if query_lower in searchable:
                results.append({k: v for k, v in data.items() if k != "content"})
        except Exception:
            continue
    return sorted(results, key=lambda r: r.get("date", "") or r.get("created_at", ""), reverse=True)


def search_reports(query: str) -> list[dict]:
    """Search PDF reports by keyword."""
    return _search(query, source_type="pdf")


def search_video_reports(query: str) -> list[dict]:
    """Search video reports by keyword."""
    return _search(query, source_type="video")


def load_report(report_id: str) -> dict | None:
    path = REPORTS_DIR / f"{report_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
