"""Send Slack notifications via Incoming Webhook."""

import logging

import requests

log = logging.getLogger(__name__)


def send_slack(webhook_url: str, index_url: str, result: dict) -> None:
    """
    Post a Slack message summarising what changed.
    `result` is the dict returned by site_monitor.check_for_updates().
    """
    lines = [f"*【新着情報】METIページが更新されました*\n<{index_url}|ページを開く>"]
    lines.append(f"最終更新日: {result['last_update_date']}")

    if result["new_items"]:
        lines.append("\n*新しい会議資料:*")
        for item in result["new_items"]:
            lines.append(f"• <{item['href']}|{item['text']}>")
    elif result.get("date_changed"):
        lines.append("\n（リンクリストの変更はありませんが、更新日が変わっています。内容を確認してください）")

    payload = {"text": "\n".join(lines)}
    resp = requests.post(webhook_url, json=payload, timeout=10)
    resp.raise_for_status()
    log.info("Slack notification sent (%d new items)", len(result.get("new_items", [])))
