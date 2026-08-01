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

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("WebexChatOps")

WEBEX_API = "https://webexapis.com/v1"


def _api_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def send_webex_reply(text: str, *, token: str, room_id: str) -> None:
    """Send a markdown message to the Webex room."""
    resp = requests.post(
        f"{WEBEX_API}/messages",
        headers=_api_headers(token),
        json={"roomId": room_id, "markdown": text},
        timeout=15,
    )
    if resp.status_code != 200:
        logger.error("Webex send failed: %s — %s", resp.status_code, resp.text)


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
        send_webex_reply(
            "**📋 Available Commands**\n\n"
            "In group spaces, @mention the bot first: `@Hermes /ping`\n\n"
            "`/ping` — Check if the bot is alive\n"
            "`/pnl` — Live Dhan P&L + Holdings\n"
            "`/paper` — Paper Trading Portfolio Status\n"
            "`/journal` — Today's Trade Journal Report\n"
            "`/stats` — Analytics summary (win rate, failure tags)\n"
            "`/plan` — Current Evening Trade Plan\n"
            "`/morning` — Morning gap + refined trade plan\n"
            "`/kill` — ⚠️ Emergency shutdown (flatten + halt)\n"
            "`/help` — Show this message",
            token=token,
            room_id=room_id,
        )
    else:
        send_webex_reply(
            f"❓ Unknown command `{cmd}`.\nType `/help` for available commands.",
            token=token,
            room_id=room_id,
        )


def get_bot_identity(token: str) -> dict[str, str]:
    """Return bot id and display name."""
    resp = requests.get(f"{WEBEX_API}/people/me", headers=_api_headers(token), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return {"id": data["id"], "displayName": data.get("displayName", "Bot")}


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
        retry_after = resp.headers.get("Retry-After", "5")
        logger.warning("Webex rate limit (429) — backing off %ss", retry_after)
        return []
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
) -> None:
    """Handle one incoming message if it contains a command."""
    if message.get("personId") == bot_id:
        return
    text = (message.get("text") or "").strip()
    if "/" not in text:
        return
    handle_command(text, token=token, room_id=room_id)


def poll_once(
    *,
    token: str,
    room_id: str,
    room_type: str,
    bot_id: str,
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
        process_message(message, bot_id=bot_id, token=token, room_id=room_id)

    if newest_id != state.get("last_message_id"):
        state["last_message_id"] = newest_id
        save_poll_state(state_file, state)


def run_poll_loop(
    *,
    token: str,
    room_id: str,
    poll_interval_secs: float = 2.0,
    state_file: Path | None = None,
) -> None:
    """Blocking poll loop — run as a long-lived systemd service."""
    if state_file is None:
        var_dir = Path(os.environ.get("HERMES_VAR_DIR", "var"))
        state_file = var_dir / "state" / "webex_poll_state.json"

    bot = get_bot_identity(token)
    bot_id = bot["id"]
    room_type = get_room_type(token, room_id)

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
    logger.info("Bot running as %s", bot["displayName"])
    if room_type == "group":
        logger.info("Group space: users must @mention the bot (e.g. @Hermes /ping)")

    state = load_poll_state(state_file)
    stop = False

    def _shutdown(signum, frame):
        nonlocal stop
        logger.info("Shutdown signal received — saving poll state.")
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
                state=state,
                state_file=state_file,
            )
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                retry = int(exc.response.headers.get("Retry-After", 10))
                logger.warning("Rate limited — sleeping %ds", retry)
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
