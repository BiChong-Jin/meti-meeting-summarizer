"""
Daily checker — run this via cron to monitor the page and notify Slack.

Cron example (every day at 9:00 AM):
  0 9 * * * /path/to/.venv/bin/python /path/to/checker.py

Or set INDEX_URL and SLACK_WEBHOOK as environment variables:
  export INDEX_URL=https://www.meti.go.jp/shingikai/enecho/denryoku_gas/jisedai_kiban/index.html
  export SLACK_WEBHOOK=https://hooks.slack.com/services/XXX/YYY/ZZZ
"""

import logging
import os
import sys

from dotenv import load_dotenv

import requests
from notifier import send_slack
from site_monitor import check_for_updates, save_state, PageStructureChanged

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

INDEX_URL = os.environ.get(
    "MONITOR_URL",
    "https://www.meti.go.jp/shingikai/enecho/denryoku_gas/jisedai_kiban/index.html",
)
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK", "")


def _send_error_slack(message: str) -> None:
    """Send a Slack alert about a checker failure."""
    if SLACK_WEBHOOK:
        payload = {"text": f"*【監視エラー】*\n{message}\n対象: {INDEX_URL}"}
        try:
            requests.post(SLACK_WEBHOOK, json=payload, timeout=10)
        except Exception:
            log.exception("Failed to send error notification to Slack")


def main():
    if not SLACK_WEBHOOK:
        log.error("SLACK_WEBHOOK is not set in .env")
        sys.exit(1)

    log.info("Checking: %s", INDEX_URL)

    try:
        result = check_for_updates(INDEX_URL)
    except PageStructureChanged as e:
        log.error("Page structure changed: %s", e)
        _send_error_slack(f"ページ構成が変更されました。スクレイパーの修正が必要です。\n{e}")
        sys.exit(1)
    except (requests.ConnectionError, requests.Timeout) as e:
        log.error("Network error after retries: %s", e)
        _send_error_slack(f"ネットワークエラー（リトライ後も失敗）:\n{e}")
        sys.exit(1)

    log.info("Last update date: %s", result["last_update_date"])

    if result["has_update"]:
        log.info("Update detected! New items: %d", len(result["new_items"]))
        send_slack(SLACK_WEBHOOK, INDEX_URL, result)
        log.info("Slack notification sent.")
    else:
        log.info("No updates.")

    # Always save state after a successful check
    save_state(result["last_update_date"], result["all_links"])


if __name__ == "__main__":
    main()
