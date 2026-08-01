"""
Webex ChatOps — outbound API polling (no webhooks).

Internal VMs cannot receive Webex webhook POSTs (no public URL). This module
polls webexapis.com every BOT_POLL_INTERVAL_SEC seconds, reads @mention
commands in group spaces, and replies via the Messages API.

Commands:
  /ping     — Health check
  /pnl      — Live Dhan P&L + Holdings report
  /plan     — Current Evening Trade Plan
  /morning  — Force a Morning Gap Prediction
  /paper    — Paper Trading Portfolio Status
  /journal  — Today's Trade Journal Report
  /stats    — Analytics summary (win rate, trades, failure tags)
  /kill     — Emergency shutdown — flatten all positions and halt agent
  /help     — Command list

In group spaces users must @mention the bot: @Hermes /ping
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from hermes.config import get_config
from hermes.integrations.webex_cards import (
    help_menu_markdown,
    help_message_attachments,
    hermes_about_markdown,
)
from hermes.integrations.webex_websocket import WebexCardActionListener

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("WebexChatOps")

WEBEX_API = "https://webexapis.com/v1"


class WebexRateLimited(Exception):
    """Raised when Webex returns HTTP 429; caller should sleep retry_after seconds."""

    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"Rate limited for {retry_after:.0f}s")


def _parse_retry_after(response: requests.Response, *, default: float = 10.0) -> float:
    raw = response.headers.get("Retry-After", str(default))
    try:
        return max(float(raw), 1.0)
    except ValueError:
        return default


def _api_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def send_webex_message(
    *,
    token: str,
    room_id: str,
    markdown: str,
    attachments: list[dict] | None = None,
    _retries: int = 1,
) -> None:
    """Send a markdown message, optionally with adaptive card attachments."""
    payload: dict = {"roomId": room_id, "markdown": markdown}
    if attachments:
        payload["attachments"] = attachments
    resp = requests.post(
        f"{WEBEX_API}/messages",
        headers=_api_headers(token),
        json=payload,
        timeout=15,
    )
    if resp.status_code == 429 and _retries > 0:
        retry = _parse_retry_after(resp)
        logger.warning("Webex send rate limited — sleeping %.0fs and retrying", retry)
        time.sleep(retry)
        send_webex_message(
            token=token,
            room_id=room_id,
            markdown=markdown,
            attachments=attachments,
            _retries=_retries - 1,
        )
        return
    if resp.status_code != 200:
        logger.error("Webex send failed: %s — %s", resp.status_code, resp.text)


def send_webex_reply(text: str, *, token: str, room_id: str) -> None:
    """Send a markdown message to the Webex room."""
    send_webex_message(token=token, room_id=room_id, markdown=text)


def send_help_card(
    *,
    token: str,
    room_id: str,
    include_about: bool = True,
    bot_name: str = "Hermes",
    bot_email: str = "",
) -> None:
    """Send help as text (with personEmail tags) plus a separate button card."""
    parts = []
    if include_about:
        parts.append(hermes_about_markdown(bot_email=bot_email, bot_name=bot_name))
        parts.append("---")
    parts.append(help_menu_markdown(bot_email=bot_email, bot_name=bot_name))
    # Webex API: mentions cannot be combined with attachments in one message.
    send_webex_message(token=token, room_id=room_id, markdown="\n\n".join(parts))
    send_webex_message(
        token=token,
        room_id=room_id,
        markdown="**Command menu** — tap a button below:",
        attachments=help_message_attachments(bot_name=bot_name),
    )


# Natural-language phrases → show help (group spaces: must @mention the bot)
HELP_PHRASES = (
    "help",
    "what can you do",
    "what do you do",
    "what are you",
    "how do i use",
    "how to use",
    "commands",
    "options",
    "menu",
    "hello",
    "hi",
    "hey",
)

# Shorthand after @Hermes (no slash required)
COMMAND_ALIASES: dict[str, str] = {
    "ping": "/ping",
    "plan": "/plan",
    "evening": "/plan",
    "morning": "/morning",
    "paper": "/paper",
    "journal": "/journal",
    "stats": "/stats",
    "help": "/help",
    "about": "/help",
    "pnl": "/pnl",
    "kill": "/kill",
}


def _strip_mentions(text: str) -> str:
    """Remove @mention tokens (Webex encodes mentions in plain text)."""
    import re

    cleaned = re.sub(r"<[^>|]+\|[^>]+>", "", text)
    cleaned = re.sub(r"@\S+", "", cleaned)
    return cleaned.strip()


def _normalize_user_text(text: str, *, bot_name: str = "Hermes") -> str:
    """Strip Webex mention markup and leading bot display name."""
    import re

    cleaned = _strip_mentions(text)
    cleaned = re.sub(rf"(?i)^{re.escape(bot_name)}\s+", "", cleaned.strip())
    return cleaned.strip().lower()


def extract_command_from_text(text: str, *, bot_name: str = "Hermes") -> str | None:
    """Parse @Hermes /plan, @Hermes plan, or Hermes plan into a slash command."""
    slash_idx = text.find("/")
    if slash_idx != -1:
        return text[slash_idx:].strip().lower().split()[0]

    cleaned = _normalize_user_text(text, bot_name=bot_name)
    if not cleaned:
        return None
    for word in cleaned.split():
        alias = COMMAND_ALIASES.get(word)
        if alias:
            return alias
    return None


def is_help_or_unknown(text: str, *, bot_name: str = "Hermes") -> bool:
    """True when the user @mentioned the bot but did not send a known command."""
    if extract_command_from_text(text, bot_name=bot_name):
        return False
    cleaned = _normalize_user_text(text, bot_name=bot_name)
    if not cleaned:
        return True
    return any(phrase in cleaned for phrase in HELP_PHRASES) or len(cleaned.split()) <= 6


def run_script(command_list: list[str]) -> None:
    """Run a local Python subprocess."""
    try:
        subprocess.run(command_list, check=True)
    except subprocess.CalledProcessError:
        logger.exception("Command failed: %s", " ".join(command_list))


def handle_command(text: str, *, token: str, room_id: str) -> None:
    """Route a command string to the appropriate action."""
    cmd_start = text.find("/")
    if cmd_start == -1:
        return
    cmd = text[cmd_start:].strip().lower().split()[0]

    logger.info("Processing command: '%s'", cmd)
    cfg = get_config()

    if cmd == "/ping":
        from hermes.clock import now_ist

        send_webex_reply(
            f"🏓 **Pong!** Hermes is online ({now_ist().strftime('%Y-%m-%d %H:%M:%S IST')}).",
            token=token,
            room_id=room_id,
        )
    elif cmd == "/pnl":
        send_webex_reply("🔄 Fetching live Dhan P&L...", token=token, room_id=room_id)
        run_script([sys.executable, "-m", "hermes.cli", "pnl"])
    elif cmd == "/plan":
        send_webex_reply("🔄 Generating Evening Trade Plan...", token=token, room_id=room_id)
        run_script([sys.executable, "-m", "hermes.integrations.notify_webex", "evening"])
    elif cmd == "/morning":
        send_webex_reply("🔄 Fetching Global Signals...", token=token, room_id=room_id)
        run_script([sys.executable, "-m", "hermes.cli", "morning", "--force"])
    elif cmd == "/paper":
        send_webex_reply(
            f"📊 **Paper Trading Portfolio**\n\n"
            f"- **Mode:** {cfg.trading_mode.upper()}\n"
            f"- **Starting Capital:** ₹{cfg.paper_starting_capital:,.0f}\n"
            f"- **Max Daily Trades:** {cfg.max_daily_trades}\n"
            f"- **Max Daily Loss:** ₹{cfg.max_daily_loss_rupees:,.0f}\n"
            f"- **Risk Per Trade:** {cfg.risk_per_trade_pct * 100:.1f}%\n\n"
            f"Use `/journal` to view today's trades, `/stats` for analytics.",
            token=token,
            room_id=room_id,
        )
    elif cmd == "/journal":
        send_webex_reply("📖 **Fetching Today's Trade Journal...**", token=token, room_id=room_id)
        run_script([
            sys.executable,
            "-c",
            "from hermes.analytics.trade_journal_report import generate_journal_report; "
            "print(generate_journal_report([]))",
        ])
    elif cmd == "/kill":
        send_webex_reply(
            "🛑 **KILL SWITCH ACTIVATED** — Writing sentinel file. Agent will flatten positions and halt.",
            token=token,
            room_id=room_id,
        )
        try:
            from hermes.clock import now_ist
            from hermes import artifacts

            artifacts.write_kill_switch(f"Kill requested via ChatOps at {now_ist().isoformat()}")
            logger.warning("KILL_SWITCH file created via /kill ChatOps command.")
        except Exception as exc:
            send_webex_reply(f"⚠️ Failed to write kill switch: {exc}", token=token, room_id=room_id)
    elif cmd == "/stats":
        send_webex_reply("📈 **Fetching Analytics Summary...**", token=token, room_id=room_id)
        run_script([
            sys.executable,
            "-c",
            "from hermes.analytics.analytics_report import print_stats_summary; print_stats_summary()",
        ])
    elif cmd == "/help":
        bot = get_bot_identity(token)
        send_help_card(
            token=token,
            room_id=room_id,
            include_about=True,
            bot_name=bot.get("displayName", "Hermes"),
            bot_email=bot.get("email", ""),
        )
    else:
        send_webex_reply(
            f"❓ Unknown command `{cmd}`.",
            token=token,
            room_id=room_id,
        )
        bot = get_bot_identity(token)
        send_help_card(
            token=token,
            room_id=room_id,
            include_about=False,
            bot_name=bot.get("displayName", "Hermes"),
            bot_email=bot.get("email", ""),
        )


def get_bot_identity(token: str) -> dict[str, str]:
    """Return bot id, display name, and email (for Webex mention tags)."""
    resp = requests.get(f"{WEBEX_API}/people/me", headers=_api_headers(token), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    emails = data.get("emails") or []
    return {
        "id": data["id"],
        "displayName": data.get("displayName", "Bot"),
        "email": emails[0] if emails else "",
    }


def handle_attachment_action(action: dict[str, Any], *, token: str, room_id: str) -> None:
    """Run a slash command from an adaptive card Action.Submit."""
    inputs = action.get("inputs") or {}
    cmd = inputs.get("command") or inputs.get("callback_keyword", "")
    if isinstance(cmd, str) and cmd.startswith("callback___"):
        cmd = cmd.replace("callback___", "", 1)
    if not cmd:
        logger.warning("Card action missing command: %s", inputs)
        return
    if not str(cmd).startswith("/"):
        cmd = f"/{cmd}"
    logger.info("Card action command: %s", cmd)
    handle_command(str(cmd), token=token, room_id=room_id)


def get_room_type(token: str, room_id: str) -> str:
    """Return room type: 'group' or 'direct'."""
    resp = requests.get(f"{WEBEX_API}/rooms/{room_id}", headers=_api_headers(token), timeout=15)
    resp.raise_for_status()
    return resp.json().get("type", "group")


def list_room_messages(
    token: str,
    room_id: str,
    *,
    room_type: str = "group",
    max_messages: int = 20,
) -> list[dict[str, Any]]:
    """
    List messages the bot is allowed to read.

    Group spaces require mentionedPeople=me or Webex returns 403.
    """
    params: dict[str, Any] = {"roomId": room_id, "max": max_messages}
    if room_type == "group":
        params["mentionedPeople"] = "me"

    resp = requests.get(
        f"{WEBEX_API}/messages",
        headers=_api_headers(token),
        params=params,
        timeout=15,
    )
    if resp.status_code == 403:
        logger.error(
            "403 Forbidden listing messages — ensure users @mention the bot in group spaces "
            "and the bot is a member of the room."
        )
        return []
    if resp.status_code == 429:
        retry_after = _parse_retry_after(resp)
        raise WebexRateLimited(retry_after)
    resp.raise_for_status()
    return resp.json().get("items", [])


def load_poll_state(state_file: Path) -> dict[str, Any]:
    if state_file.exists():
        with open(state_file, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_poll_state(state_file: Path, state: dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def collect_new_messages(
    messages: list[dict[str, Any]],
    last_message_id: str | None,
) -> list[dict[str, Any]]:
    """Return new messages oldest-first (API returns newest-first)."""
    if not messages:
        return []

    if not last_message_id:
        return []

    new_messages: list[dict[str, Any]] = []
    for message in messages:
        if message.get("id") == last_message_id:
            break
        new_messages.append(message)
    new_messages.reverse()
    return new_messages


def process_message(
    message: dict[str, Any],
    *,
    bot_id: str,
    token: str,
    room_id: str,
    bot_name: str = "Hermes",
    bot_email: str = "",
) -> None:
    """Handle @mention messages: slash commands, aliases, or help."""
    if message.get("personId") == bot_id:
        return
    text = (message.get("text") or "").strip()

    cmd = extract_command_from_text(text, bot_name=bot_name)
    if cmd:
        handle_command(cmd, token=token, room_id=room_id)
        return

    if is_help_or_unknown(text, bot_name=bot_name):
        logger.info("Help request: '%s'", text[:80])
        send_help_card(
            token=token,
            room_id=room_id,
            include_about=True,
            bot_name=bot_name,
            bot_email=bot_email,
        )


def poll_once(
    *,
    token: str,
    room_id: str,
    room_type: str,
    bot_id: str,
    bot_name: str,
    bot_email: str,
    state: dict[str, Any],
    state_file: Path,
) -> None:
    """Single poll iteration: fetch, process new commands, persist state."""
    messages = list_room_messages(token, room_id, room_type=room_type)
    if not messages:
        return

    newest_id = messages[0]["id"]

    if not state.get("last_message_id"):
        state["last_message_id"] = newest_id
        save_poll_state(state_file, state)
        logger.info("Initialized poll state (skipping message backlog).")
        return

    for message in collect_new_messages(messages, state["last_message_id"]):
        process_message(
            message,
            bot_id=bot_id,
            token=token,
            room_id=room_id,
            bot_name=bot_name,
            bot_email=bot_email,
        )

    if newest_id != state.get("last_message_id"):
        state["last_message_id"] = newest_id
        save_poll_state(state_file, state)


def run_poll_loop(
    *,
    token: str,
    room_id: str,
    poll_interval_secs: float = 5.0,
    state_file: Path | None = None,
) -> None:
    """Blocking poll loop — run as a long-lived systemd service."""
    if state_file is None:
        var_dir = Path(os.environ.get("HERMES_VAR_DIR", "var"))
        state_file = var_dir / "state" / "webex_poll_state.json"

    bot = get_bot_identity(token)
    bot_id = bot["id"]
    bot_name = bot.get("displayName", "Hermes")
    bot_email = bot.get("email", "")
    room_type = get_room_type(token, room_id)

    card_listener: WebexCardActionListener | None = None
    cfg = get_config()
    if cfg.bot_use_websocket:
        card_listener = WebexCardActionListener(
            token=token,
            room_id=room_id,
            bot_id=bot_id,
            bot_email=bot_email,
            on_card_action=lambda action: handle_attachment_action(
                action, token=token, room_id=room_id
            ),
        )
        try:
            card_listener.start()
        except Exception:
            logger.exception("Failed to start Webex WebSocket — card buttons disabled")
            card_listener = None

    room_resp = requests.get(
        f"{WEBEX_API}/rooms/{room_id}",
        headers=_api_headers(token),
        timeout=15,
    )
    room_title = room_resp.json().get("title", room_id) if room_resp.ok else room_id

    logger.info(
        "Listening in room %s (%s, type=%s) — poll every %.1fs",
        room_title,
        room_id,
        room_type,
        poll_interval_secs,
    )
    logger.info("Bot running as %s <%s>", bot["displayName"], bot_email or "unknown")
    if cfg.bot_use_websocket and card_listener is not None:
        logger.info("Webex WebSocket enabled — adaptive card buttons active")
    elif cfg.bot_use_websocket:
        logger.warning("Webex WebSocket unavailable — use typed @mention commands")
    if room_type == "group":
        logger.info("Group space: users must @mention the bot (e.g. @Hermes plan)")

    state = load_poll_state(state_file)
    stop = False

    def _shutdown(signum, frame):
        nonlocal stop
        logger.info("Shutdown signal received — saving poll state.")
        if card_listener is not None:
            card_listener.stop()
        save_poll_state(state_file, state)
        stop = True

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while not stop:
        try:
            poll_once(
                token=token,
                room_id=room_id,
                room_type=room_type,
                bot_id=bot_id,
                bot_name=bot_name,
                bot_email=bot_email,
                state=state,
                state_file=state_file,
            )
        except WebexRateLimited as exc:
            logger.warning(
                "Webex rate limit (429) — sleeping %.0fs before next poll",
                exc.retry_after,
            )
            time.sleep(exc.retry_after)
            continue
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                retry = _parse_retry_after(exc.response)
                logger.warning("Rate limited — sleeping %.0fs", retry)
                time.sleep(retry)
                continue
            logger.exception("Poll iteration failed")
        except requests.RequestException:
            logger.exception("Poll iteration failed")
        time.sleep(poll_interval_secs)

    logger.info("Webex poll loop stopped.")


def main() -> None:
    cfg = get_config()
    token = cfg.webex_token
    room_id = cfg.webex_room_id

    if not token or not room_id:
        logger.error("Missing WEBEX_TOKEN or WEBEX_ROOM_ID in .env")
        sys.exit(1)

    state_path = Path(cfg.bot_state_file) if cfg.bot_state_file else None
    run_poll_loop(
        token=token,
        room_id=room_id,
        poll_interval_secs=float(cfg.bot_poll_interval_sec),
        state_file=state_path,
    )


if __name__ == "__main__":
    main()
