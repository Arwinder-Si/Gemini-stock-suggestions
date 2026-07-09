"""
Webex Notification Service
===========================
Sends trading signals and screener results to a Webex Teams room.

Environment variables (set via GitHub Secrets):
    WEBEX_TOKEN   — Webex Bot access token
    WEBEX_ROOM_ID — Target Webex room ID

Usage:
    python notify_webex.py evening    # Send evening screener results
    python notify_webex.py morning    # Send pre-market trade plan reminder
"""

import json
import os
import sys
import io

# Fix Windows console emoji printing
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import pandas as pd
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

WEBEX_API = "https://webexapis.com/v1/messages"


def send_webex_message(markdown: str) -> bool:
    """Send a markdown-formatted message to the configured Webex room."""
    token = os.environ.get("WEBEX_TOKEN")
    room_id = os.environ.get("WEBEX_ROOM_ID")

    if not token or not room_id:
        print("ERROR: WEBEX_TOKEN or WEBEX_ROOM_ID not set.")
        return False

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "roomId": room_id,
        "markdown": markdown,
    }

    resp = requests.post(WEBEX_API, headers=headers, json=payload, timeout=15)
    if resp.status_code == 200:
        print(f"Webex message sent successfully.")
        return True
    else:
        print(f"Webex send failed: {resp.status_code} — {resp.text}")
        return False


def build_evening_message() -> str:
    """Build the evening screener results message."""
    msg = "## 📊 NSE Breakout Screener — Evening Report\n\n"

    # Load screener results
    if not os.path.exists("screener_results.csv"):
        return msg + "⚠️ No screener results found. Pipeline may have failed."

    df = pd.read_csv("screener_results.csv")

    if df.empty:
        return msg + "No stocks scored above 50/100 today. **No trades tomorrow.**"

    # Top candidates (70+ only go into trade plan)
    top = df[df["Score"] >= 70]
    watchlist = df[(df["Score"] >= 50) & (df["Score"] < 70)]

    if not top.empty:
        msg += "### 🟢 Trade Plan Candidates (Score ≥ 70)\n\n"
        msg += "| # | Stock | Score | Sector | Vol | RSI | Dist EMA20 |\n"
        msg += "|---|-------|-------|--------|-----|-----|------------|\n"
        for i, (_, row) in enumerate(top.iterrows(), 1):
            msg += (
                f"| {i} | **{row['Stock']}** | {row['Score']}/100 | "
                f"{row['Sector']} | {row['Vol_Ratio']}x | {row['RSI']:.0f} | "
                f"+{row['Dist_EMA20']}% |\n"
            )
        msg += "\n"
    else:
        msg += "### 🔴 No stocks scored 70+. **No trades tomorrow.**\n\n"

    if not watchlist.empty:
        msg += "### 🟡 Watchlist (Score 50-69)\n\n"
        watch_names = ", ".join(watchlist["Stock"].tolist()[:8])
        msg += f"{watch_names}\n\n"

    # News sentiment highlights
    if os.path.exists("news_features.csv"):
        nf = pd.read_csv("news_features.csv")
        pos = nf[nf["sentiment_7d"] > 0.1]
        neg = nf[nf["sentiment_7d"] < -0.1]
        reg = nf[nf["has_neg_reg_news_7d"] == True]

        if not pos.empty or not neg.empty or not reg.empty:
            msg += "### 📰 News Sentiment\n"
            if not pos.empty:
                for _, r in pos.nlargest(3, "sentiment_7d").iterrows():
                    msg += f"- ✅ **{r['symbol']}**: {r['sentiment_7d']:+.2f} — _{r['top_headline'][:60]}_\n"
            if not neg.empty:
                for _, r in neg.iterrows():
                    msg += f"- ❌ **{r['symbol']}**: {r['sentiment_7d']:+.2f} — _{r['top_headline'][:60]}_\n"
            if not reg.empty:
                for _, r in reg.iterrows():
                    msg += f"- ⚠️ **{r['symbol']}**: REGULATORY RISK\n"
            msg += "\n"

    msg += "---\n_Run at market close. Trade plan auto-generated._"
    return msg


def build_morning_message() -> str:
    """Build the pre-market reminder with today's trade plan and global context."""
    msg = "## ☀️ PRE-MARKET BRIEFING\n\n"
    
    # 1. Add Global Signals Context
    import market_db
    try:
        conn = market_db.get_connection()
        global_df = pd.read_sql("SELECT * FROM global_signals WHERE date = (SELECT MAX(date) FROM global_signals)", conn)
        pred = market_db.get_latest_gap_prediction()
        conn.close()
        
        if not global_df.empty and pred:
            msg += "**📊 GLOBAL OVERNIGHT SIGNALS**\n\n"
            for _, row in global_df.iterrows():
                trend = "🟢" if row['change_pct'] > 0 else "🔴"
                if row['signal_name'] in ['Crude Oil', 'US 10Y Yield', 'Dollar Index']:
                    trend = "🔴" if row['change_pct'] > 0 else "🟢" 
                    
                msg += f"**{row['signal_name']}**: {row['value']:,.2f} ({trend} {row['change_pct']:+.2f}%)\n\n"
                
            msg += f"**🔮 GAP PREDICTION:** {pred['prediction_pct']:+.2f}% — {pred['bias']}\n\n---\n\n"
    except Exception as e:
        print(f"Error loading global context: {e}")

    # 2. Add Trade Plan with Setup Details
    msg += "**🎯 TODAY'S TRADE PLAN & SETUPS**\n\n"
    if not os.path.exists("trade_plan.json") or not os.path.exists("screener_results.csv"):
        msg += "⚠️ No trade plan found. Run the evening pipeline first.\n\n"
    else:
        try:
            sdf = pd.read_csv("screener_results.csv")
            
            # Separate >= 70 (Trade Plan) and 60-69 (Watchlist)
            trade_plan = sdf[sdf['Score'] >= 70].copy()
            watchlist = sdf[(sdf['Score'] >= 60) & (sdf['Score'] < 70)].copy()

            if trade_plan.empty:
                msg += "🔴 No trades today. Screener found zero 70+ setups yesterday.\n\n"
            else:
                # Top Candidate Details
                top_row = trade_plan.iloc[0]
                msg += f"**🏆 #1 — {top_row['Stock']} (Score: {top_row['Score']}/100)**\n"
                msg += f"**Price:** ₹{top_row['Close']:,.2f}\n"
                msg += f"**Volume:** {top_row['Vol_Ratio']}x average\n"
                msg += f"**RSI:** {top_row['RSI']}\n"
                msg += f"**Dist from 20EMA:** +{top_row['Dist_EMA20']}%\n"
                msg += f"_High-momentum {top_row['Sector']} candidate showing excellent relative volume._\n\n"

                # Rest of the Trade Plan
                if len(trade_plan) > 1:
                    msg += "**Other Primary Candidates (Score >= 70)**\n\n"
                    for _, row in trade_plan.iloc[1:].iterrows():
                        msg += f"**{row['Stock']}** | Score: {row['Score']}/100 | Vol: {row['Vol_Ratio']}x | RSI: {row['RSI']}\n\n"

            # Watchlist
            if not watchlist.empty:
                msg += "**👀 WATCHLIST (Strong but below 70 threshold)**\n\n"
                for idx, row in enumerate(watchlist.itertuples(), start=1):
                    msg += f"**{idx}. {row.Stock}** | Score: {row.Score} | Sector: {row.Sector} | Vol: {row.Vol_Ratio}x | RSI: {row.RSI}\n\n"
                    
        except Exception as e:
            print(f"Error loading setup details: {e}")
            msg += "⚠️ Failed to load detailed setups.\n\n"

    msg += "---\n\n"
    msg += "**⏰ TRADING PLAYBOOK**\n\n"
    msg += "**9:15 – 9:30 AM** (Observation Phase)\nLet the 15-min ORB candle form. DO NOT TRADE.\n\n"
    msg += "**9:30 – 9:45 AM** (Primary Entry Window)\n🟢 Watch for price to break above the ORB high with volume.\n\n"
    msg += "**10:30 – 11:30 AM** (Defense Phase)\n🛡️ Start trailing stops to breakeven.\n\n"
    msg += "**11:30 AM+** (Exit Zone)\n🛑 No new entries. Let runners hit TP or trailing SL.\n\n"

    msg += "---\n_Bot is online. Good luck today! 🚀_"
    return msg


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python notify_webex.py [evening|morning]")
        sys.exit(1)

    mode = sys.argv[1].lower()

    if mode == "evening":
        message = build_evening_message()
    elif mode == "morning":
        message = build_morning_message()
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)

    print(f"\n--- Message Preview ---\n{message}\n--- End Preview ---\n")
    send_webex_message(message)
