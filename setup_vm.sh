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
python news_sentiment.py
python comprehensive_screener.py
python intraday_trigger.py
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
echo "🤖 Installing Webex ChatOps Listener..."
SERVICE_FILE="/etc/systemd/system/nse-bot-listener.service"
sudo bash -c "cat << 'EOF' > $SERVICE_FILE
[Unit]
Description=NSE Webex ChatOps Listener
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/venv/bin/python $(pwd)/webex_listener.py
Restart=always
RestartSec=5
Environment=PATH=$(pwd)/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[Install]
WantedBy=multi-user.target
EOF"
sudo systemctl daemon-reload
sudo systemctl enable nse-bot-listener.service
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
echo "CRITICAL: Do not forget to create your .env file on the VM:"
echo "cp .env.example .env"
echo "nano .env"
echo "---------------------------------------------------"
