"""Shared report storage — save and load generated reports via SQLite."""

import json
import logging
import time
import uuid

from db import get_connection

log = logging.getLogger(__name__)


def find_existing_report(title: str, date: str, source_type: str) -> str | None:
    """Return the ID of an existing report with the same title, date, and source_type, or None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM reports WHERE title = ? AND date = ? AND source_type = ?",
            (title or "(タイトルなし)", date or "", source_type),
        ).fetchone()
    return row["id"] if row else None


def save_report(
    title: str,
    date: str,
    content: str,
    sources: list[str],
    source_type: str = "pdf",
) -> str:
    """Save a report and return its ID. Skips insert if a report with the same title, date, and source_type already exists."""
    existing_id = find_existing_report(title, date, source_type)
    if existing_id:
        log.info("Report already exists: %s (id=%s)", title, existing_id)
        return existing_id

    report_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    log.info("Saving new report: %s (id=%s, type=%s)", title, report_id, source_type)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO reports (id, title, date, content, sources, source_type, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                report_id,
                title or "(タイトルなし)",
                date or "",
                content,
                json.dumps(sources, ensure_ascii=False),
                source_type,
                time.strftime("%Y-%m-%dT%H:%M:%S"),
            ),
        )
    return report_id


def _row_to_meta(row) -> dict:
    """Convert a sqlite3.Row to a metadata dict (no content)."""
    return {
        "id": row["id"],
        "title": row["title"],
        "date": row["date"],
        "sources": json.loads(row["sources"]),
        "source_type": row["source_type"],
        "created_at": row["created_at"],
    }


REPORTS_PER_PAGE = 20


def _all_reports_meta(source_type: str | None = None, page: int = 1) -> list[dict]:
    """Load report metadata with pagination, optionally filtered by source_type."""
    offset = (page - 1) * REPORTS_PER_PAGE
    with get_connection() as conn:
        if source_type:
            rows = conn.execute(
                "SELECT id, title, date, sources, source_type, created_at FROM reports WHERE source_type = ? ORDER BY COALESCE(NULLIF(date, ''), created_at) DESC LIMIT ? OFFSET ?",
                (source_type, REPORTS_PER_PAGE, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, date, sources, source_type, created_at FROM reports ORDER BY COALESCE(NULLIF(date, ''), created_at) DESC LIMIT ? OFFSET ?",
                (REPORTS_PER_PAGE, offset),
            ).fetchall()
    return [_row_to_meta(r) for r in rows]


def count_reports(source_type: str) -> int:
    """Return total count of reports for a source_type."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM reports WHERE source_type = ?", (source_type,)
        ).fetchone()
    return row["cnt"]


def list_reports(page: int = 1) -> list[dict]:
    """Return PDF report metadata sorted by meeting date newest-first."""
    return _all_reports_meta(source_type="pdf", page=page)


def list_video_reports(page: int = 1) -> list[dict]:
    """Return video report metadata sorted by meeting date newest-first."""
    return _all_reports_meta(source_type="video", page=page)


def _search(query: str, source_type: str, page: int = 1) -> list[dict]:
    pattern = f"%{query}%"
    offset = (page - 1) * REPORTS_PER_PAGE
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT id, title, date, sources, source_type, created_at FROM reports
               WHERE source_type = ?
               AND (LOWER(title) LIKE LOWER(?) OR LOWER(date) LIKE LOWER(?) OR LOWER(content) LIKE LOWER(?) OR LOWER(sources) LIKE LOWER(?))
               ORDER BY COALESCE(NULLIF(date, ''), created_at) DESC
               LIMIT ? OFFSET ?""",
            (source_type, pattern, pattern, pattern, pattern, REPORTS_PER_PAGE, offset),
        ).fetchall()
    return [_row_to_meta(r) for r in rows]


def search_reports(query: str, page: int = 1) -> list[dict]:
    """Search PDF reports by keyword."""
    return _search(query, source_type="pdf", page=page)


def search_video_reports(query: str, page: int = 1) -> list[dict]:
    """Search video reports by keyword."""
    return _search(query, source_type="video", page=page)


def load_report(report_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "title": row["title"],
        "date": row["date"],
        "content": row["content"],
        "sources": json.loads(row["sources"]),
        "source_type": row["source_type"],
        "created_at": row["created_at"],
    }
