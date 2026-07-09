# DhanHQ Intraday Trading Signal System

This is a robust, production-ready Python backend system for generating NSE intraday equity trading signals using the DhanHQ API. It runs an Opening Range Breakout (ORB) strategy.

> **IMPORTANT COMPLIANCE NOTE**
> This system ONLY generates alerts via Telegram and logs signals to a local CSV file. It does **not** implement any order placement or auto-execution functionality. This intentional limitation ensures compliance with SEBI's retail algorithmic trading rules, avoiding issues related to static IP whitelisting, Algo-ID tagging, and broker approvals required for full auto-execution.

## Features

- **Live Market Feed integration:** Connects to DhanHQ's WebSocket feed in Quote mode.
- **Tick-to-Candle aggregation:** Efficiently converts live ticks into 1-minute OHLCV candles.
- **Producer-Consumer architecture:** Designed for multi-strategy support via concurrent thread worker queues.
- **ORB Strategy:** Fully configurable Opening Range Breakout strategy.
- **Telegram Notifications:** Instant alerts on entry points, stop losses, and take profits.
- **CSV Logging:** Logs all generated signals locally for record-keeping.
- **Backtesting Module:** Simulates the ORB strategy using historical intraday data to evaluate edge.

## Setup Instructions

1. **Clone the repository.**
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Configure Environment:**
   Copy the example environment file and fill in your details:
   ```bash
   cp .env.example .env
   ```
   *Edit `.env` with your Dhan Client ID, Access Token, and Telegram Bot credentials.*

4. **Telegram Bot Setup (If you don't have one):**
   - Open Telegram and message `@BotFather`.
   - Send `/newbot` and follow the prompts to get your `TELEGRAM_BOT_TOKEN`.
   - Send a message to your new bot.
   - Go to `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` to find your `chat_id` (look for `"chat":{"id":...}`). Set this as `TELEGRAM_CHAT_ID`.

## Usage

### Running Live Signals (Market Hours)
To run the live signal generator:
```bash
python main.py
```

### Running Backtests (Any Time)
To test the strategy on historical data:
```bash
python backtest.py
```
*Make sure to configure the dates and symbol within the backtest script.*
