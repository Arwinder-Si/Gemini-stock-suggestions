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
python global_signals.py
python notify_webex.py morning
EOF
chmod +x run_morning.sh

cat << 'EOF' > run_evening.sh
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
python update_security_ids.py
python news_sentiment.py
python comprehensive_screener.py
python intraday_trigger.py
python comprehensive_screener.py --universe small
python intraday_trigger.py --universe small
python -c "import market_db; market_db.save_screener_results('screener_results.csv'); market_db.save_news_results('news_features.csv')"
python notify_webex.py evening
EOF
chmod +x run_evening.sh

cat << 'EOF' > run_live_bot.sh
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
# Run the live bot for exactly 6.5 hours (9:00 AM to 3:30 PM), then kill it
timeout 23400 python main.py
EOF
chmod +x run_live_bot.sh

cat << 'EOF' > run_pnl.sh
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
python notify_webex.py pnl
EOF
chmod +x run_pnl.sh

# 4. Set up ChatOps Listener Daemon (Systemd)
echo "🤖 Installing Webex ChatOps Listener (Flask webhook server)..."
SERVICE_FILE="/etc/systemd/system/nse-bot-listener.service"
sudo bash -c "cat << EOFSERVICE > $SERVICE_FILE
[Unit]
Description=Hermes Webex ChatOps Listener
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
EnvironmentFile=$(pwd)/.env
ExecStart=$(pwd)/venv/bin/python $(pwd)/webex_listener.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOFSERVICE"
sudo systemctl daemon-reload
sudo systemctl enable nse-bot-listener.service

# Ensure BOT_PUBLIC_URL is set so Webex can deliver inbound commands
ENV_FILE="$(pwd)/.env"
if [ -f "$ENV_FILE" ]; then
    if ! grep -qE '^BOT_PUBLIC_URL=.+' "$ENV_FILE"; then
        echo "⚙️  BOT_PUBLIC_URL not set — detecting public IP for webhook registration..."
        PUBLIC_IP=$(curl -s --max-time 5 https://ifconfig.me/ip 2>/dev/null \
            || curl -s --max-time 5 https://icanhazip.com 2>/dev/null \
            || echo "")
        if [ -n "$PUBLIC_IP" ]; then
            echo "" >> "$ENV_FILE"
            echo "# Public URL for Webex webhook delivery (required for /ping, /pnl, etc.)" >> "$ENV_FILE"
            echo "BOT_PUBLIC_URL=http://${PUBLIC_IP}:5050" >> "$ENV_FILE"
            echo "✅ Added BOT_PUBLIC_URL=http://${PUBLIC_IP}:5050 to .env"
            echo "   If webhook registration fails, use HTTPS instead (e.g. ngrok http 5050)."
        else
            echo "⚠️  Could not detect public IP. Add BOT_PUBLIC_URL to .env manually, then run:"
            echo "   sudo systemctl restart nse-bot-listener.service"
        fi
    else
        echo "✅ BOT_PUBLIC_URL already configured in .env"
    fi
else
    echo "⚠️  No .env file found. Create one from .env.example before using ChatOps."
fi

sudo systemctl restart nse-bot-listener.service

# Open firewall port for Webex webhooks
echo "🔓 Opening firewall port 5050 for Webex webhooks..."
sudo ufw allow 5050/tcp 2>/dev/null || true

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
echo "For ChatOps commands (/ping, /pnl, /plan) to work, set:"
echo "  BOT_PUBLIC_URL=https://YOUR_PUBLIC_IP:5050"
echo "  (or an ngrok HTTPS URL if behind NAT / no public IP)"
echo ""
echo "Verify the listener:"
echo "  curl http://localhost:5050/health"
echo "  sudo journalctl -u nse-bot-listener.service -n 20 --no-pager"
echo "  (look for: Webhook registered: .../webhook)"
echo "---------------------------------------------------"
