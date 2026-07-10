import os
import sys
import time
import requests
import subprocess
import logging
from config import get_config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("WebexListener")

def send_webex_reply(text: str, room_id: str, token: str) -> None:
    url = "https://webexapis.com/v1/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "roomId": room_id,
        "markdown": text
    }
    requests.post(url, json=payload, headers=headers)

def run_script(command_list, room_id, token):
    """Run a local script and reply with success or failure."""
    try:
        # We don't necessarily need to capture output if the script already sends its own Webex msg
        # but for things like /ping we might reply directly.
        subprocess.run(command_list, check=True)
        # If the script successfully runs, we assume it sent its message to Webex directly.
    except subprocess.CalledProcessError as e:
        send_webex_reply(f"⚠️ **Error executing command**: `{' '.join(command_list)}` failed.", room_id, token)

def main():
    cfg = get_config()
    webex_token = os.getenv("WEBEX_TOKEN")
    room_id = os.getenv("WEBEX_ROOM_ID")

    if not webex_token or not room_id:
        logger.error("Missing WEBEX_TOKEN or WEBEX_ROOM_ID in environment.")
        sys.exit(1)

    url = "https://webexapis.com/v1/messages"
    headers = {
        "Authorization": f"Bearer {webex_token}",
        "Content-Type": "application/json"
    }
    
    logger.info("Initializing Webex ChatOps Listener...")
    
    # Get the latest message ID to set as our starting watermark
    last_processed_id = None
    try:
        resp = requests.get(url, headers=headers, params={"roomId": room_id, "max": 1})
        if resp.status_code == 200 and resp.json().get('items'):
            last_processed_id = resp.json()['items'][0]['id']
    except Exception as e:
        logger.warning(f"Failed to fetch initial watermark: {e}")

    logger.info("Listening for commands (/pnl, /plan, /morning, /ping)...")

    while True:
        try:
            resp = requests.get(url, headers=headers, params={"roomId": room_id, "max": 10})
            if resp.status_code == 200:
                messages = resp.json().get('items', [])
                
                # Process from oldest to newest in the batch
                new_messages = []
                for msg in messages:
                    if msg['id'] == last_processed_id:
                        break
                    new_messages.append(msg)
                
                for msg in reversed(new_messages):
                    last_processed_id = msg['id']
                    
                    # Ignore messages from the bot itself (if possible)
                    # We'll just check if it starts with '/'
                    text = msg.get('text', '').strip().lower()
                    
                    if text.startswith('/'):
                        logger.info(f"Received command: {text}")
                        
                        if text == '/ping':
                            send_webex_reply("🏓 **Pong!** The AI Trading Bot VM is online and listening.", room_id, webex_token)
                        elif text == '/pnl':
                            send_webex_reply("🔄 Fetching live Dhan P&L...", room_id, webex_token)
                            run_script(["python", "notify_webex.py", "pnl"], room_id, webex_token)
                        elif text == '/plan':
                            send_webex_reply("🔄 Generating Evening Trade Plan...", room_id, webex_token)
                            run_script(["python", "notify_webex.py", "evening"], room_id, webex_token)
                        elif text == '/morning':
                            send_webex_reply("🔄 Fetching Global Signals...", room_id, webex_token)
                            run_script(["python", "global_signals.py"], room_id, webex_token)
                            run_script(["python", "notify_webex.py", "morning"], room_id, webex_token)
                        else:
                            send_webex_reply(f"❓ Unknown command `{text}`.\nAvailable: `/pnl`, `/plan`, `/morning`, `/ping`", room_id, webex_token)
                            
        except Exception as e:
            logger.error(f"Polling error: {e}")
            
        time.sleep(3) # Poll every 3 seconds

if __name__ == "__main__":
    main()
