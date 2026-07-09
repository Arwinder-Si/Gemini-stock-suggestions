"""
Telegram notifier — sends signal alerts via the Telegram Bot HTTP API.

Uses a persistent httpx.Client for connection reuse.
"""

from __future__ import annotations

import logging

import httpx

from models import Signal

logger = logging.getLogger(__name__)

# Persistent HTTP client (connection pooling, keep-alive)
_client = httpx.Client(timeout=10.0)


def send_telegram_alert(signal: Signal, bot_token: str, chat_id: str) -> None:
    """
    Posts a formatted signal message to a Telegram chat.

    Does nothing if credentials are empty (useful for local testing).
    """
    if not bot_token or not chat_id:
        logger.debug("Skipping Telegram alert for %s: credentials missing.", signal.symbol)
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    text = (
        f"🚨 *ORB {signal.direction} SIGNAL* 🚨\n"
        f"*Symbol:* {signal.symbol}\n"
        f"*Entry:* {signal.entry}\n"
        f"*SL:* {signal.sl}\n"
        f"*TP:* {signal.tp}\n"
        f"*Reason:* {signal.reason}\n"
        f"*Time:* {signal.timestamp}"
    )

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }

    try:
        response = _client.post(url, json=payload)
        response.raise_for_status()
        logger.info("Telegram alert sent for %s.", signal.symbol)
    except httpx.HTTPStatusError as e:
        logger.error("Telegram HTTP %s: %s", e.response.status_code, e.response.text)
    except Exception:
        logger.exception("Failed to send Telegram alert for %s", signal.symbol)
