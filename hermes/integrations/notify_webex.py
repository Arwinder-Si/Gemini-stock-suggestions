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
from hermes.clock import now_ist, trading_date_ist
from hermes.domain.earnings_calendar import load_calendar, refresh_buckets

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

WEBEX_API = "https://webexapis.com/v1/messages"


def _append_earnings_watchlist(msg: str, *, session: str) -> str:
    """session: 'tomorrow' (evening) or 'today' (morning)."""
    cal = load_calendar()
    if not cal:
        return msg
    cal = refresh_buckets(cal, trading_date_ist())
    key = "result_tomorrow" if session == "tomorrow" else "result_today"
    symbols = cal.get(key) or []
    if not symbols:
        return msg

    title = "Tomorrow" if session == "tomorrow" else "Today"
    msg += f"### 📅 Results {title}\n\n"
    msg += "_High volatility around result announcements — tighten risk or skip if setup is weak._\n\n"
    for symbol in symbols:
        entry = (cal.get("entries") or {}).get(symbol, {})
        rd = entry.get("result_date", "—")
        src = entry.get("source", "")
        msg += f"- **{symbol}** — {rd}"
        if src:
            msg += f" _({src})_"
        msg += "\n"
    msg += "\n"
    return msg


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


def build_evening_message(universe="large") -> str:
    """Build the evening screener results message."""
    title = "Large/Mid Cap" if universe == "large" else "Small Cap"
    msg = f"## 📊 NSE Breakout Screener — {title} Report\n\n"
    
    if universe == "small":
        msg += "⚠️ **DANGER ZONE:** Small caps are highly volatile. Expect wide bid-ask spreads and sudden fakeouts. Strictly adhere to risk limits.\n\n"

    # Load screener results
    csv_file = "screener_results_smallcap.csv" if universe == "small" else "screener_results.csv"
    if not os.path.exists(csv_file):
        return msg + f"⚠️ No {csv_file} found. Pipeline may have failed."

    df = pd.read_csv(csv_file)

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

    msg = _append_earnings_watchlist(msg, session="tomorrow")

    msg += "---\n_Run at market close. Trade plan auto-generated._"
    return msg


def build_morning_message(universe="large") -> str:
    """Build the pre-market reminder with today's trade plan and global context."""
    today_str = now_ist().strftime("%B %d, %Y")
    title = "Large/Mid Cap" if universe == "large" else "Small Cap"
    msg = f"## ☀️ PRE-MARKET BRIEFING ({today_str}) - {title}\n\n"

    if universe == "small":
        msg += "⚠️ **DANGER ZONE:** Small caps are highly volatile. Expect wide bid-ask spreads and sudden fakeouts. Strictly adhere to risk limits.\n\n"

    # 1. Add Global Signals Context
    from hermes.data import market_db
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

    msg = _append_earnings_watchlist(msg, session="today")

    # 2. Morning-refined trade plan (combines screener + news + global gap)
    msg += "**🎯 TODAY'S REFINED TRADE PLAN**\n\n"
    morning_plan_path = "morning_trade_plan.json"
    if os.path.exists(morning_plan_path):
        try:
            with open(morning_plan_path, encoding="utf-8") as f:
                morning_plan = json.load(f)
            rankings = morning_plan.get("rankings", [])
            if not rankings:
                msg += "🔴 Morning refiner found no stocks above the score threshold.\n\n"
            else:
                msg += (
                    f"_Regime: {morning_plan.get('market_regime', 'N/A')} | "
                    f"Gap: {morning_plan.get('gap_prediction_pct', 0):+.2f}% "
                    f"({morning_plan.get('gap_bias', '')})_\n\n"
                )
                msg += "| # | Stock | Morning | Screener | Sentiment | Sector |\n"
                msg += "|---|-------|---------|----------|-----------|--------|\n"
                for i, row in enumerate(rankings, 1):
                    sent = row.get("sentiment_7d", 0)
                    sent_icon = "🟢" if sent > 0.05 else ("🔴" if sent < -0.05 else "⚪")
                    result_flag = " 📅" if row.get("earnings_result_today") else ""
                    msg += (
                        f"| {i} | **{row['symbol']}**{result_flag} | {row['morning_score']:.0f} | "
                        f"{row['screener_score']} | {sent_icon} {sent:+.2f} | {row.get('sector', '')} |\n"
                    )
                msg += "\n"
        except Exception as e:
            print(f"Error loading morning plan: {e}")
            msg += "⚠️ Failed to load morning_trade_plan.json.\n\n"
    else:
        msg += "⚠️ No morning_trade_plan.json — run `python -m hermes.cli morning` first.\n\n"

    # 3. Fallback evening screener detail (if CSV available)
    csv_file = "screener_results_smallcap.csv" if universe == "small" else "screener_results.csv"
    if os.path.exists(csv_file):
        try:
            sdf = pd.read_csv(csv_file)
            watchlist = sdf[(sdf["Score"] >= 60) & (sdf["Score"] < 70)].copy()
            if not watchlist.empty:
                msg += "**👀 WATCHLIST (Screener 60–69, not in morning plan)**\n\n"
                for idx, row in enumerate(watchlist.itertuples(), start=1):
                    msg += (
                        f"**{idx}. {row.Stock}** | Score: {row.Score} | "
                        f"Sector: {row.Sector} | Vol: {row.Vol_Ratio}x\n\n"
                    )
        except Exception as e:
            print(f"Error loading watchlist: {e}")

    msg += "---\n\n"
    msg += "**⏰ TRADING PLAYBOOK**\n\n"
    if universe == "small":
        msg += "**9:15 – 9:45 AM** (Observation Phase)\n"
        msg += "Let the 30-min ORB candle form. DO NOT TRADE.\n\n"
        msg += "**9:45 – 10:15 AM** (Primary Entry Window)\n"
        msg += "🟢 Watch for price to break above the 30m ORB high with massive volume (>3.0x).\n\n"
    else:
        msg += "**9:15 – 9:30 AM** (Observation Phase)\n"
        msg += "Let the 15-min ORB candle form. DO NOT TRADE.\n\n"
        msg += "**9:30 – 9:45 AM** (Primary Entry Window)\n"
        msg += "🟢 Watch for price to break above the ORB high with volume.\n\n"
        
    msg += "**10:30 – 11:30 AM** (Defense Phase)\n🛡️ Start trailing stops to breakeven.\n\n"
    msg += "**11:30 AM+** (Exit Zone)\n🛑 No new entries. Let runners hit TP or trailing SL.\n\n"

    msg += "---\n_Bot is online. Good luck today! 🚀_"
    return msg


def build_pnl_message() -> str:
    """Connect to Dhan API, fetch today's positions, and build a P&L report."""
    from hermes.config import get_config
    from hermes.integrations.auth_manager import get_fresh_dhan_token
    import datetime
    
    cfg = get_config()
    token = get_fresh_dhan_token(cfg.dhan_client_id, cfg.dhan_pin, cfg.dhan_totp_secret)
    
    try:
        from dhanhq import dhanhq, DhanContext
        context = DhanContext(cfg.dhan_client_id, token)
        dhan = dhanhq(context)
        
        resp = dhan.get_positions()
        if resp.get('status') != 'success':
            return "⚠️ **Failed to fetch P&L from Dhan API.**\n" + str(resp)
            
        positions = resp.get('data', [])
        
        today_str = now_ist().strftime("%B %d, %Y")
        msg = f"## 💰 END OF DAY P&L REPORT ({today_str})\n\n"
        
        if not positions:
            msg += "No trades were taken today.\n"
            return msg
            
        total_charges = 0.0
        total_realized = 0.0
        total_unrealized = 0.0
        
        msg += "**Trade Breakdown:**\n\n"
        for pos in positions:
            symbol = pos.get('tradingSymbol', 'UNKNOWN')
            realized = float(pos.get('realizedProfit', 0.0))
            unrealized = float(pos.get('unrealizedProfit', 0.0))
            net_qty = pos.get('netQty', 0)
            
            segment = pos.get('exchangeSegment', '')
            product = pos.get('productType', '')
            buy_val = float(pos.get('dayBuyValue', 0.0))
            sell_val = float(pos.get('daySellValue', 0.0))
            turnover = buy_val + sell_val
            
            # Estimate Charges
            brokerage = min(40.0, 0.0003 * turnover) if 'EQ' in segment else 40.0
            if 'FNO' in segment:
                stt = 0.00125 * sell_val
                txn_chg = 0.0005 * turnover
                stamp = 0.00003 * buy_val
            else:
                stt = 0.00025 * sell_val if product == 'INTRADAY' else 0.001 * turnover
                txn_chg = 0.0000325 * turnover
                stamp = 0.00003 * buy_val if product == 'INTRADAY' else 0.00015 * buy_val
                
            sebi = 0.000001 * turnover
            gst = 0.18 * (brokerage + txn_chg + sebi)
            pos_charges = brokerage + stt + txn_chg + stamp + gst + sebi
            total_charges += pos_charges
            net_profit = realized - pos_charges
            
            total_realized += realized
            total_unrealized += unrealized
            
            if net_qty == 0:
                icon = "🟢" if net_profit > 0 else "🔴"
                msg += f"**{symbol}** (Closed): {icon} Gross: ₹{realized:.2f} | Net: ₹{net_profit:.2f} *(Chg: ₹{pos_charges:.2f})*\n"
            else:
                icon = "🟢" if unrealized > 0 else "🔴"
                msg += f"**{symbol}** (Open {net_qty}): {icon} Gross MTM: ₹{unrealized:.2f}\n"

        net_pnl = (total_realized + total_unrealized) - total_charges
        
        msg += "---\n\n"
        msg += f"**Gross Realized:** ₹{total_realized:.2f}\n"
        msg += f"**Gross Unrealized:** ₹{total_unrealized:.2f}\n"
        msg += f"**Est. Charges & Taxes:** ₹{total_charges:.2f}\n"
        msg += f"### 🏆 NET P&L: ₹{net_pnl:.2f}\n\n"
        
        # --- HOLDINGS SECTION ---
        holdings_resp = dhan.get_holdings()
        if holdings_resp.get('status') == 'success':
            holdings = holdings_resp.get('data', [])
            if holdings:
                msg += "\n---\n\n## 💼 PORTFOLIO HOLDINGS\n\n"
                total_portfolio_mtm = 0.0
                total_invested = 0.0
                total_current = 0.0
                
                for h in holdings:
                    symbol = h.get('tradingSymbol', 'UNKNOWN')
                    qty = h.get('totalQty', 0)
                    buy_price = h.get('avgCostPrice', 0.0)
                    ltp = h.get('lastTradedPrice', 0.0)
                    
                    if qty > 0:
                        invested = qty * buy_price
                        current_val = qty * ltp
                        mtm = current_val - invested
                        
                        total_invested += invested
                        total_current += current_val
                        total_portfolio_mtm += mtm
                        
                        emoji = "🟢" if mtm >= 0 else "🔴"
                        msg += f"**{symbol}** (Qty: {qty}): {emoji} ₹{mtm:,.2f}\n"
                        
                port_emoji = "🏆" if total_portfolio_mtm >= 0 else "🩸"
                msg += f"\n**Total Invested:** ₹{total_invested:,.2f}\n"
                msg += f"**Current Value:** ₹{total_current:,.2f}\n"
                msg += f"### {port_emoji} TOTAL PORTFOLIO MTM: ₹{total_portfolio_mtm:,.2f}\n"

        return msg
        
    except Exception as e:
        return f"⚠️ **Error generating P&L report:** {e}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python notify_webex.py [evening|morning|pnl]")
        sys.exit(1)

    mode = sys.argv[1].lower()

    if mode == "evening":
        for univ in ["large", "small"]:
            msg = build_evening_message(universe=univ)
            print(f"\n--- Message Preview ({univ}) ---\n{msg}\n--- End Preview ---\n")
            send_webex_message(msg)
    elif mode == "morning":
        for univ in ["large", "small"]:
            msg = build_morning_message(universe=univ)
            print(f"\n--- Message Preview ({univ}) ---\n{msg}\n--- End Preview ---\n")
            send_webex_message(msg)
    elif mode == "pnl":
        msg = build_pnl_message()
        print(f"\n--- Message Preview ---\n{msg}\n--- End Preview ---\n")
        send_webex_message(msg)
    else:
        print("Invalid mode. Use 'evening', 'morning', or 'pnl'.")
        sys.exit(1)
