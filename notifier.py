"""
Webex notifier — sends live intraday signal alerts via the Webex Teams API.

Uses a persistent httpx.Client for connection reuse.
"""

from __future__ import annotations

import logging

import httpx

from models import Signal

logger = logging.getLogger(__name__)

# Persistent HTTP client (connection pooling, keep-alive)
_client = httpx.Client(timeout=10.0)


def send_webex_alert(signal: Signal, bot_token: str, room_id: str) -> None:
    """
    Posts a formatted live trade signal to a Webex room.

    Does nothing if credentials are empty (useful for local testing).
    """
    if not bot_token or not room_id:
        logger.debug("Skipping Webex alert for %s: credentials missing.", signal.symbol)
        return

    url = "https://webexapis.com/v1/messages"

    text = (
        f"🚨 **ORB {signal.direction} SIGNAL** 🚨\n"
        f"- **Symbol:** {signal.symbol}\n"
        f"- **Entry:** {signal.entry}\n"
        f"- **SL:** {signal.sl}\n"
        f"- **TP:** {signal.tp}\n"
        f"- **Reason:** {signal.reason}\n"
        f"- **Time:** {signal.timestamp}"
    )

    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "roomId": room_id,
        "markdown": text,
    }

    try:
        response = _client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info("Webex alert sent for %s.", signal.symbol)
    except httpx.HTTPStatusError as e:
        logger.error("Webex HTTP %s: %s", e.response.status_code, e.response.text)
    except Exception:
        logger.exception("Failed to send Webex alert for %s", signal.symbol)
