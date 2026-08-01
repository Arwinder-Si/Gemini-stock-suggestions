#!/bin/bash
# Restart the Hermes Webex polling ChatOps service.
# Run on the VM from the repo root:
#   bash scripts/configure_bot_polling.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Copy .env.example to .env first."
    exit 1
fi

if ! grep -qE '^WEBEX_TOKEN=.+' "$ENV_FILE"; then
    echo "ERROR: WEBEX_TOKEN not set in .env"
    exit 1
fi

if ! grep -qE '^WEBEX_ROOM_ID=.+' "$ENV_FILE"; then
    echo "ERROR: WEBEX_ROOM_ID not set in .env"
    exit 1
fi

if ! grep -qE '^BOT_POLL_INTERVAL_SEC=' "$ENV_FILE"; then
    echo "BOT_POLL_INTERVAL_SEC=5" >> "$ENV_FILE"
    echo "Added BOT_POLL_INTERVAL_SEC=5"
fi

sudo systemctl restart nse-bot-listener.service
sleep 2
sudo journalctl -u nse-bot-listener.service -n 20 --no-pager

echo ""
echo "In group spaces, @mention the bot: @Hermes /ping"
echo "To re-process recent messages after a logic change:"
echo "  rm -f var/state/webex_poll_state.json && sudo systemctl restart nse-bot-listener.service"
