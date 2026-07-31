"""
Webex ChatOps Listener — Webhook-based interactive bot.

Runs a lightweight Flask server on the VM. Webex pushes incoming messages
to this server via a registered webhook. The bot then executes commands
and replies directly in the Webex room.

Commands:
  /ping     — Health check
  /pnl      — Live Dhan P&L + Holdings report
  /plan     — Current Evening Trade Plan
  /morning  — Force a Morning Gap Prediction
  /paper    — Paper Trading Portfolio Status
  /journal  — Today's Trade Journal Report
  /stats    — Analytics summary (win rate, trades, failure tags)
  /kill     — Emergency shutdown — flatten all positions and halt agent
"""

import sys
import subprocess
import logging
import os
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from config import get_config

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("WebexListener")

app = Flask(__name__)

# Load config once at startup
cfg = get_config()
WEBEX_TOKEN = cfg.webex_token
ROOM_ID = cfg.webex_room_id
BOT_PUBLIC_URL = cfg.bot_public_url.rstrip("/")
BOT_PORT = cfg.bot_port
BOT_ID = None  # Set during init


def send_webex_reply(text: str) -> None:
    """Send a markdown message to the Webex room."""
    url = "https://webexapis.com/v1/messages"
    headers = {
        "Authorization": f"Bearer {WEBEX_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"roomId": ROOM_ID, "markdown": text}
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code != 200:
        logger.error(f"Webex send failed: {resp.status_code} — {resp.text}")


def run_script(command_list: list) -> None:
    """Run a local Python script."""
    try:
        subprocess.run(command_list, check=True)
    except subprocess.CalledProcessError as e:
        send_webex_reply(f"⚠️ **Error executing command**: `{' '.join(command_list)}` failed.")


def handle_command(text: str) -> None:
    """Route a command string to the appropriate action."""
    # Strip everything before the first '/' (handles @mentions in group rooms)
    cmd_start = text.find('/')
    if cmd_start == -1:
        return
    cmd = text[cmd_start:].strip().lower()

    logger.info(f"Processing command: '{cmd}'")

    if cmd == '/ping':
        send_webex_reply("🏓 **Pong!** The AI Trading Bot VM is online and listening.")
    elif cmd == '/pnl':
        send_webex_reply("🔄 Fetching live Dhan P&L...")
        run_script(["python", "notify_webex.py", "pnl"])
    elif cmd == '/plan':
        send_webex_reply("🔄 Generating Evening Trade Plan...")
        run_script(["python", "notify_webex.py", "evening"])
    elif cmd == '/morning':
        send_webex_reply("🔄 Fetching Global Signals...")
        run_script(["python", "global_signals.py"])
        run_script(["python", "notify_webex.py", "morning"])
    elif cmd == '/paper':
        capital = cfg.paper_starting_capital
        mode = cfg.trading_mode.upper()
        send_webex_reply(
            f"📊 **Paper Trading Portfolio**\n\n"
            f"- **Mode:** {mode}\n"
            f"- **Starting Capital:** ₹{capital:,.0f}\n"
            f"- **Max Daily Trades:** {cfg.max_daily_trades}\n"
            f"- **Max Daily Loss:** ₹{cfg.max_daily_loss_rupees:,.0f}\n"
            f"- **Risk Per Trade:** {cfg.risk_per_trade_pct * 100:.1f}%\n\n"
            f"Use `/journal` to view today's trades, `/stats` for analytics."
        )
    elif cmd == '/journal':
        send_webex_reply("📖 **Fetching Today's Trade Journal...**")
        run_script(["python", "-c", "from trade_journal_report import generate_journal_report; print(generate_journal_report([]))"])
    elif cmd == '/kill':
        send_webex_reply("🛑 **KILL SWITCH ACTIVATED** — Writing sentinel file. Agent will flatten positions and halt.")
        try:
            with open("KILL_SWITCH", "w") as f:
                from clock import now_ist
                f.write(f"Kill requested via ChatOps at {now_ist().isoformat()}")
            logger.warning("KILL_SWITCH file created via /kill ChatOps command.")
        except Exception as e:
            send_webex_reply(f"⚠️ Failed to write kill switch: {e}")
    elif cmd == '/stats':
        send_webex_reply("📈 **Fetching Analytics Summary...**")
        run_script(["python", "-c", "from analytics_report import print_stats_summary; print_stats_summary()"])
    elif cmd == '/help':
        send_webex_reply(
            "**📋 Available Commands:**\n\n"
            "`/ping` — Check if the bot is alive\n"
            "`/pnl` — Live Dhan P&L + Holdings\n"
            "`/paper` — Paper Trading Portfolio Status\n"
            "`/journal` — Today's Trade Journal Report\n"
            "`/stats` — Analytics summary (win rate, failure tags)\n"
            "`/plan` — Current Evening Trade Plan\n"
            "`/morning` — Morning Gap Prediction\n"
            "`/kill` — ⚠️ Emergency shutdown (flatten + halt)\n"
            "`/help` — Show this message"
        )
    else:
        send_webex_reply(
            f"❓ Unknown command `{cmd}`.\n"
            "Type `/help` for available commands."
        )



@app.route("/webhook", methods=["POST"])
def webhook():
    """Receive incoming message notifications from Webex."""
    data = request.json
    if not data:
        return jsonify({"status": "no data"}), 400

    # Webex webhooks only send the message ID, not the content.
    # We need to fetch the full message using the API.
    message_id = data.get("data", {}).get("id")
    person_id = data.get("data", {}).get("personId")

    # Ignore messages sent by the bot itself
    if person_id == BOT_ID:
        return jsonify({"status": "ignored (self)"}), 200

    if not message_id:
        return jsonify({"status": "no message id"}), 200

    # Fetch the actual message text
    headers = {
        "Authorization": f"Bearer {WEBEX_TOKEN}",
        "Content-Type": "application/json"
    }
    msg_resp = requests.get(
        f"https://webexapis.com/v1/messages/{message_id}",
        headers=headers
    )

    if msg_resp.status_code != 200:
        logger.error(f"Failed to fetch message: {msg_resp.status_code}")
        return jsonify({"status": "fetch failed"}), 200

    text = msg_resp.json().get("text", "").strip()
    logger.info(f"Incoming message: '{text}'")

    if '/' in text:
        handle_command(text)

    return jsonify({"status": "ok"}), 200


@app.route("/health", methods=["GET"])
def health():
    """Simple health check endpoint."""
    return jsonify({"status": "healthy", "bot": "Hermes Trading Bot"}), 200


def register_webhook(public_url: str) -> None:
    """Register (or update) the Webex webhook to point to our Flask server."""
    headers = {
        "Authorization": f"Bearer {WEBEX_TOKEN}",
        "Content-Type": "application/json"
    }

    # First, list existing webhooks and delete any old ones for this bot
    resp = requests.get("https://webexapis.com/v1/webhooks", headers=headers)
    if resp.status_code == 200:
        for wh in resp.json().get("items", []):
            if wh.get("name") == "hermes-chatops":
                requests.delete(
                    f"https://webexapis.com/v1/webhooks/{wh['id']}",
                    headers=headers
                )
                logger.info(f"Deleted old webhook: {wh['id']}")

    # Create a new webhook
    payload = {
        "name": "hermes-chatops",
        "targetUrl": f"{public_url}/webhook",
        "resource": "messages",
        "event": "created",
        "filter": f"roomId={ROOM_ID}"
    }
    resp = requests.post(
        "https://webexapis.com/v1/webhooks",
        json=payload,
        headers=headers
    )
    if resp.status_code in (200, 201):
        logger.info(f"✅ Webhook registered: {public_url}/webhook")
    else:
        logger.error(f"Failed to register webhook: {resp.status_code} — {resp.text}")
        sys.exit(1)


def init_bot():
    """Initialize bot identity and register webhook."""
    global BOT_ID
    headers = {
        "Authorization": f"Bearer {WEBEX_TOKEN}",
        "Content-Type": "application/json"
    }

    # Get bot identity
    me_resp = requests.get("https://webexapis.com/v1/people/me", headers=headers)
    if me_resp.status_code == 200:
        BOT_ID = me_resp.json().get("id")
        bot_name = me_resp.json().get("displayName", "Bot")
        logger.info(f"Bot identity: {bot_name}")
    else:
        logger.error(f"Failed to get bot identity: {me_resp.status_code}")
        sys.exit(1)

    if BOT_PUBLIC_URL:
        register_webhook(BOT_PUBLIC_URL)
    else:
        logger.warning(
            "BOT_PUBLIC_URL not set. Webhook not registered — "
            "interactive commands (/ping, /pnl, etc.) will not work. "
            "Add BOT_PUBLIC_URL to .env (public HTTPS URL, e.g. "
            "https://YOUR_VM_IP:5050 or an ngrok tunnel) and restart."
        )


if __name__ == "__main__":
    if not WEBEX_TOKEN or not ROOM_ID:
        logger.error("Missing WEBEX_TOKEN or WEBEX_ROOM_ID in .env")
        sys.exit(1)

    init_bot()

    logger.info(f"Starting Hermes ChatOps server on port {BOT_PORT}...")
    app.run(host="0.0.0.0", port=BOT_PORT)
