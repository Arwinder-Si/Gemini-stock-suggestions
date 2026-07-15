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


def send_webex_alert(signal: Signal, bot_token: str, room_id: str, universe: str = "large") -> None:
    """
    Posts a formatted live trade signal to a Webex room.

    Does nothing if credentials are empty (useful for local testing).
    """
    if not bot_token or not room_id:
        logger.debug("Skipping Webex alert for %s: credentials missing.", signal.symbol)
        return

    url = "https://webexapis.com/v1/messages"

    if signal.direction == "UPDATE_SL":
        text = (
            f"**🛡️ TRAILING STOP ALERT: {signal.symbol}**\n\n"
            f"**Action:** Move Stop Loss to Breakeven\n\n"
            f"**New Stop Loss:** ₹{signal.sl:,.2f}\n\n"
            f"---\n\n"
            f"Reason: {signal.reason}\n\n"
            f"Time: {signal.timestamp}"
        )
    elif signal.direction == "EXIT":
        emoji = "🟢" if signal.pnl_pct > 0 else "🔴"
        text = (
            f"**🛑 TRADE CLOSED: {signal.symbol}**\n\n"
            f"**Exit Price:** ₹{signal.entry:,.2f}\n\n"
            f"**Net PnL:** {emoji} {signal.pnl_pct:+.2f}%\n\n"
            f"---\n\n"
            f"Reason: {signal.reason}\n\n"
            f"Time: {signal.timestamp}"
        )
    else:
        univ_tag = "🎲 SMALL CAP" if universe == "small" else "📊 LARGE CAP"
        text = (
            f"**🚨 ORB {signal.direction} SIGNAL [{univ_tag}]**\n\n"
            f"**Symbol:** {signal.symbol}\n\n"
            f"**Entry:** ₹{signal.entry:,.2f}\n\n"
            f"**Stop Loss:** ₹{signal.sl:,.2f}\n\n"
            f"**Take Profit:** ₹{signal.tp:,.2f}\n\n"
            f"---\n\n"
            f"Reason: {signal.reason}\n\n"
            f"Time: {signal.timestamp}"
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
