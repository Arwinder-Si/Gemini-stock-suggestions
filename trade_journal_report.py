"""
Trade Journal Performance Reporting module.

Generates human-readable daily, weekly, and monthly trade journal summaries,
equity curve stats, and drawdown analysis.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from analytics_models import TradeJournalEntry

logger = logging.getLogger(__name__)


def generate_journal_report(entries: list[TradeJournalEntry]) -> str:
    """Generates formatted markdown summary of trade journal entries."""
    if not entries:
        return "### 📖 Trade Journal Report\nNo paper trades executed for this period."

    total_trades = len(entries)
    wins = sum(1 for e in entries if e.is_win)
    win_rate = (wins / total_trades) * 100
    total_net_pnl = sum(e.net_pnl for e in entries)
    total_charges = sum(e.total_charges for e in entries)

    lines = [
        "### 📖 Trade Journal Performance Summary",
        f"**Total Trades:** {total_trades} | **Win Rate:** {win_rate:.1f}%",
        f"**Net P&L:** ₹{total_net_pnl:,.2f} | **Total Charges:** ₹{total_charges:,.2f}",
        "",
        "| Time | Symbol | Side | Qty | Entry | Exit | Net PnL | Result | Reason |",
        "|------|--------|------|-----|-------|------|---------|--------|--------|",
    ]

    for e in entries:
        res_tag = "✅ WIN" if e.is_win else "❌ LOSS"
        side_tag = "LONG" if e.quantity > 0 else "SHORT"
        lines.append(
            f"| {e.trading_date} | {e.symbol} | {side_tag} | {e.quantity} | "
            f"₹{e.entry_price:.2f} | ₹{e.exit_price:.2f} | ₹{e.net_pnl:+.2f} | {res_tag} | {e.exit_reason} |"
        )

    return "\n".join(lines)


def generate_weekly_report(entries: list[TradeJournalEntry]) -> str:
    """Generates a weekly aggregated performance report."""
    if not entries:
        return "### 📅 Weekly Report\nNo trades this week."

    # Group by week (ISO week number)
    weeks: dict[str, list[TradeJournalEntry]] = defaultdict(list)
    for e in entries:
        try:
            dt = datetime.strptime(e.trading_date, "%Y-%m-%d")
            week_key = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
        except ValueError:
            week_key = "Unknown"
        weeks[week_key].append(e)

    lines = [
        "### 📅 Weekly Performance Summary",
        "",
        "| Week | Trades | Wins | Win Rate | Net P&L | Charges | Best Trade | Worst Trade |",
        "|------|--------|------|----------|---------|---------|------------|-------------|",
    ]

    for week_key in sorted(weeks.keys()):
        week_entries = weeks[week_key]
        count = len(week_entries)
        wins = sum(1 for e in week_entries if e.is_win)
        wr = (wins / count) * 100 if count > 0 else 0.0
        net = sum(e.net_pnl for e in week_entries)
        charges = sum(e.total_charges for e in week_entries)
        best = max(week_entries, key=lambda e: e.net_pnl)
        worst = min(week_entries, key=lambda e: e.net_pnl)

        lines.append(
            f"| {week_key} | {count} | {wins} | {wr:.0f}% | ₹{net:+,.0f} | "
            f"₹{charges:,.0f} | {best.symbol} (₹{best.net_pnl:+,.0f}) | {worst.symbol} (₹{worst.net_pnl:+,.0f}) |"
        )

    return "\n".join(lines)


def generate_monthly_report(entries: list[TradeJournalEntry]) -> str:
    """Generates a monthly aggregated performance report."""
    if not entries:
        return "### 📆 Monthly Report\nNo trades this month."

    months: dict[str, list[TradeJournalEntry]] = defaultdict(list)
    for e in entries:
        try:
            dt = datetime.strptime(e.trading_date, "%Y-%m-%d")
            month_key = dt.strftime("%Y-%m")
        except ValueError:
            month_key = "Unknown"
        months[month_key].append(e)

    lines = [
        "### 📆 Monthly Performance Summary",
        "",
        "| Month | Trades | Wins | Losses | Win Rate | Net P&L | Avg Win | Avg Loss | Profit Factor |",
        "|-------|--------|------|--------|----------|---------|---------|----------|---------------|",
    ]

    for month_key in sorted(months.keys()):
        me = months[month_key]
        count = len(me)
        wins = sum(1 for e in me if e.is_win)
        losses = count - wins
        wr = (wins / count) * 100 if count > 0 else 0.0
        net = sum(e.net_pnl for e in me)

        win_pnls = [e.net_pnl for e in me if e.is_win]
        loss_pnls = [e.net_pnl for e in me if not e.is_win]
        avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
        avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0
        total_gains = sum(win_pnls)
        total_losses = abs(sum(loss_pnls))
        pf = total_gains / total_losses if total_losses > 0 else float("inf") if total_gains > 0 else 0.0

        lines.append(
            f"| {month_key} | {count} | {wins} | {losses} | {wr:.0f}% | ₹{net:+,.0f} | "
            f"₹{avg_win:+,.0f} | ₹{avg_loss:+,.0f} | {pf:.2f} |"
        )

    return "\n".join(lines)


def compute_equity_curve(entries: list[TradeJournalEntry], starting_capital: float = 1_000_000.0) -> dict:
    """Compute equity curve and drawdown metrics from journal entries.

    Returns dict with:
    - daily_equity: list of {date, equity}
    - max_drawdown_pct: peak-to-trough drawdown
    - current_drawdown_pct: current distance from peak
    - peak_equity: highest equity reached
    - best_trade: entry with largest net_pnl
    - worst_trade: entry with smallest net_pnl
    """
    if not entries:
        return {
            "daily_equity": [],
            "max_drawdown_pct": 0.0,
            "current_drawdown_pct": 0.0,
            "peak_equity": starting_capital,
            "best_trade": None,
            "worst_trade": None,
        }

    # Sort by trading_date
    sorted_entries = sorted(entries, key=lambda e: e.trading_date)

    # Aggregate daily P&L
    daily_pnl: dict[str, float] = defaultdict(float)
    for e in sorted_entries:
        daily_pnl[e.trading_date] += e.net_pnl

    # Build equity curve
    equity = starting_capital
    peak = starting_capital
    max_dd = 0.0
    daily_equity: list[dict] = []

    for date_str in sorted(daily_pnl.keys()):
        equity += daily_pnl[date_str]
        peak = max(peak, equity)
        dd = ((peak - equity) / peak) * 100 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
        daily_equity.append({"date": date_str, "equity": round(equity, 2)})

    current_dd = ((peak - equity) / peak) * 100 if peak > 0 else 0.0

    best = max(sorted_entries, key=lambda e: e.net_pnl)
    worst = min(sorted_entries, key=lambda e: e.net_pnl)

    return {
        "daily_equity": daily_equity,
        "max_drawdown_pct": round(max_dd, 2),
        "current_drawdown_pct": round(current_dd, 2),
        "peak_equity": round(peak, 2),
        "best_trade": {"symbol": best.symbol, "date": best.trading_date, "pnl": round(best.net_pnl, 2)},
        "worst_trade": {"symbol": worst.symbol, "date": worst.trading_date, "pnl": round(worst.net_pnl, 2)},
    }


def generate_equity_report(entries: list[TradeJournalEntry], starting_capital: float = 1_000_000.0) -> str:
    """Generate a markdown equity curve and drawdown summary."""
    curve = compute_equity_curve(entries, starting_capital)

    if not curve["daily_equity"]:
        return "### 📈 Equity Curve\nNo trade data available."

    final_equity = curve["daily_equity"][-1]["equity"]
    total_return = ((final_equity - starting_capital) / starting_capital) * 100

    lines = [
        "### 📈 Equity Curve Summary",
        "",
        f"- **Starting Capital:** ₹{starting_capital:,.0f}",
        f"- **Current Equity:** ₹{final_equity:,.0f}",
        f"- **Total Return:** {total_return:+.2f}%",
        f"- **Peak Equity:** ₹{curve['peak_equity']:,.0f}",
        f"- **Max Drawdown:** {curve['max_drawdown_pct']:.2f}%",
        f"- **Current Drawdown:** {curve['current_drawdown_pct']:.2f}%",
    ]

    if curve["best_trade"]:
        bt = curve["best_trade"]
        lines.append(f"- **Best Trade:** {bt['symbol']} on {bt['date']} (₹{bt['pnl']:+,.0f})")
    if curve["worst_trade"]:
        wt = curve["worst_trade"]
        lines.append(f"- **Worst Trade:** {wt['symbol']} on {wt['date']} (₹{wt['pnl']:+,.0f})")

    return "\n".join(lines)
