"""One-time migration: JSON files -> SQLite database."""

import json
from pathlib import Path

from db import get_connection


def migrate():
    with get_connection() as conn:
        # 1. Reports
        reports_dir = Path("reports")
        count = 0
        if reports_dir.exists():
            for f in reports_dir.glob("*.json"):
                data = json.loads(f.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT OR IGNORE INTO reports (id, title, date, content, sources, source_type, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        data["id"],
                        data.get("title", "(タイトルなし)"),
                        data.get("date", ""),
                        data.get("content", ""),
                        json.dumps(data.get("sources", []), ensure_ascii=False),
                        data.get("source_type", "pdf"),
                        data.get("created_at", ""),
                    ),
                )
                count += 1
        print(f"Reports migrated: {count}")

        # 2. Session cache
        cache_dir = Path("session_cache")
        count = 0
        if cache_dir.exists():
            for f in cache_dir.glob("*.json"):
                session_id = f.stem
                data = json.loads(f.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT OR IGNORE INTO session_cache (session_id, pdf_texts, summary_result, video_summary_result, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        session_id,
                        json.dumps(data.get("pdf_texts", []), ensure_ascii=False),
                        data.get("summary_result"),
                        data.get("video_summary_result"),
                        f.stat().st_mtime,
                    ),
                )
                count += 1
        print(f"Session caches migrated: {count}")

        # 3. Monitor state
        state_file = Path("monitor_state.json")
        if state_file.exists():
            data = json.loads(state_file.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR REPLACE INTO monitor_state (id, last_update_date, known_hrefs, last_checked) VALUES (1, ?, ?, ?)",
                (
                    data.get("last_update_date", ""),
                    json.dumps(data.get("known_hrefs", []), ensure_ascii=False),
                    data.get("last_checked", ""),
                ),
            )
            print("Monitor state migrated: 1")
        else:
            print("Monitor state: no file found, skipping")

        # 4. RSS seen items
        seen_file = Path("seen_items.json")
        if seen_file.exists():
            seen = json.loads(seen_file.read_text(encoding="utf-8"))
            conn.executemany(
                "INSERT OR IGNORE INTO rss_seen_items (item_id) VALUES (?)",
                [(item_id,) for item_id in seen],
            )
            print(f"RSS seen items migrated: {len(seen)}")
        else:
            print("RSS seen items: no file found, skipping")

    print("Migration complete!")


if __name__ == "__main__":
    migrate()
