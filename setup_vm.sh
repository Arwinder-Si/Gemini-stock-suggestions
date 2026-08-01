#!/bin/bash
# ==============================================================================
# NSE AI Trading Bot — VM Deployment Script
# Run this script on your Linux VM (Ubuntu/Debian) to set up 24/7 automation.
# ==============================================================================

echo "🚀 Starting VM Setup for NSE AI Trading Bot..."

# 1. Update system and install dependencies
echo "📦 Installing system dependencies (Python 3, pip, cron)..."
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip cron

# 2. Set up Python Virtual Environment
echo "🐍 Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Create wrapper scripts for Cron
echo "📝 Creating wrapper scripts..."
cat << 'EOF' > run_morning.sh
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
python -m hermes.cli morning
EOF
chmod +x run_morning.sh

cat << 'EOF' > run_evening.sh
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
python -m hermes.cli evening
EOF
chmod +x run_evening.sh

cat << 'EOF' > run_live_bot.sh
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
# Run the live bot for exactly 6.5 hours (9:00 AM to 3:30 PM), then kill it
timeout 23400 python -m hermes.cli live
EOF
chmod +x run_live_bot.sh

cat << 'EOF' > run_pnl.sh
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
python -m hermes.cli pnl
EOF
chmod +x run_pnl.sh

# 4. Set up ChatOps Polling Daemon (Systemd)
echo "🤖 Installing Webex ChatOps poller (outbound API, no webhooks)..."
SERVICE_FILE="/etc/systemd/system/nse-bot-listener.service"
sudo bash -c "cat << EOFSERVICE > $SERVICE_FILE
[Unit]
Description=Hermes Webex ChatOps Poller
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
EnvironmentFile=$(pwd)/.env
ExecStart=$(pwd)/venv/bin/python -m hermes.cli chatops
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOFSERVICE"
sudo systemctl daemon-reload
sudo systemctl enable nse-bot-listener.service

ENV_FILE="$(pwd)/.env"
if [ -f "$ENV_FILE" ]; then
    if ! grep -qE '^BOT_POLL_INTERVAL_SEC=' "$ENV_FILE"; then
        echo "" >> "$ENV_FILE"
        echo "# Webex command polling interval (seconds)" >> "$ENV_FILE"
        echo "BOT_POLL_INTERVAL_SEC=2" >> "$ENV_FILE"
        echo "✅ Added BOT_POLL_INTERVAL_SEC=2 to .env"
    fi
    if ! grep -qE '^WEBEX_TOKEN=.+' "$ENV_FILE"; then
        echo "⚠️  WEBEX_TOKEN not set — ChatOps commands will not work until .env is configured."
    fi
else
    echo "⚠️  No .env file found. Create one from .env.example before using ChatOps."
fi

sudo systemctl restart nse-bot-listener.service

# 5. Set up Crontab
# We will explicitly set the VM timezone to Asia/Kolkata so cron matches IST exactly.
echo "🕒 Setting server timezone to IST (Asia/Kolkata)..."
sudo timedatectl set-timezone Asia/Kolkata

echo "⏰ Configuring Cron Schedule..."
CRON_FILE="/tmp/bot_cron"
echo "# NSE AI Trading Bot Schedule (IST Timezone)" > $CRON_FILE
echo "# 1. Morning Briefing at 8:30 AM (Mon-Fri)" >> $CRON_FILE
echo "30 08 * * 1-5 $(pwd)/run_morning.sh >> $(pwd)/morning.log 2>&1" >> $CRON_FILE
echo "" >> $CRON_FILE
echo "# 2. Start Live Intraday Bot at 9:00 AM (Mon-Fri)" >> $CRON_FILE
echo "00 09 * * 1-5 $(pwd)/run_live_bot.sh >> $(pwd)/live_bot.log 2>&1" >> $CRON_FILE
echo "" >> $CRON_FILE
echo "# 3. End of Day P&L Report at 3:40 PM (Mon-Fri)" >> $CRON_FILE
echo "40 15 * * 1-5 $(pwd)/run_pnl.sh >> $(pwd)/pnl.log 2>&1" >> $CRON_FILE
echo "" >> $CRON_FILE
echo "# 4. Evening Screener & Report at 3:45 PM (Mon-Fri)" >> $CRON_FILE
echo "45 15 * * 1-5 $(pwd)/run_evening.sh >> $(pwd)/evening.log 2>&1" >> $CRON_FILE

crontab $CRON_FILE
rm $CRON_FILE

echo ""
echo "✅ SETUP COMPLETE!"
echo "---------------------------------------------------"
echo "Your VM is now fully configured to run 24/7."
echo ""
echo "CRITICAL: Create and configure your .env file:"
echo "  cp .env.example .env"
echo "  nano .env"
echo ""
echo "For ChatOps commands (/ping, /pnl, /plan) to work:"
echo "  1. Set WEBEX_TOKEN and WEBEX_ROOM_ID in .env"
echo "  2. Add the bot to your Webex room"
echo "  3. In group spaces, @mention the bot: @Hermes /ping"
echo ""
echo "Verify the poller:"
echo "  sudo journalctl -u nse-bot-listener.service -n 20 --no-pager"
echo "  (look for: Listening in room ... poll every 2.0s)"
echo "---------------------------------------------------"
