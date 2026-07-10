#!/bin/bash
# Configure BOT_PUBLIC_URL and restart the Hermes ChatOps listener.
# Run on the VM from the repo root:
#   bash scripts/configure_bot_webhook.sh
#   bash scripts/configure_bot_webhook.sh https://your-ngrok-url.ngrok-free.app

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Copy .env.example to .env first."
    exit 1
fi

if [ -n "${1:-}" ]; then
    PUBLIC_URL="${1%/}"
elif grep -qE '^BOT_PUBLIC_URL=.+' "$ENV_FILE"; then
    PUBLIC_URL=$(grep '^BOT_PUBLIC_URL=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
    PUBLIC_URL="${PUBLIC_URL%/}"
    echo "Using existing BOT_PUBLIC_URL=$PUBLIC_URL"
else
    PUBLIC_IP=$(curl -s --max-time 5 https://ifconfig.me/ip 2>/dev/null \
        || curl -s --max-time 5 https://icanhazip.com 2>/dev/null \
        || echo "")
    if [ -z "$PUBLIC_IP" ]; then
        echo "ERROR: Could not detect public IP. Pass URL explicitly:"
        echo "  bash scripts/configure_bot_webhook.sh https://YOUR_HOST:5050"
        exit 1
    fi
    PUBLIC_URL="http://${PUBLIC_IP}:5050"
fi

if grep -q '^BOT_PUBLIC_URL=' "$ENV_FILE"; then
    sed -i.bak "s|^BOT_PUBLIC_URL=.*|BOT_PUBLIC_URL=${PUBLIC_URL}|" "$ENV_FILE"
    rm -f "${ENV_FILE}.bak"
else
    echo "" >> "$ENV_FILE"
    echo "BOT_PUBLIC_URL=${PUBLIC_URL}" >> "$ENV_FILE"
fi

echo "Set BOT_PUBLIC_URL=${PUBLIC_URL}"
sudo systemctl restart nse-bot-listener.service
sleep 2
sudo journalctl -u nse-bot-listener.service -n 15 --no-pager

echo ""
echo "If you do not see 'Webhook registered', try HTTPS (ngrok http 5050) and re-run:"
echo "  bash scripts/configure_bot_webhook.sh https://<ngrok-host>"
