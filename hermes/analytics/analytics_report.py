"""
Analytics Report — periodic strategy performance reports.

Generates weekly and monthly analytics summaries covering:
- Strategy-wise win rate and P&L
- Sector-wise performance
- Regime-wise performance
- Top failure tag frequencies
- Concrete improvement suggestions

Deliverable via Webex (/stats command) and CLI.
"""

from __future__ import annotations

import sys
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass

from hermes.data.analytics_models import PaperTrade, FailureAnalysis, TradeJournalEntry
from hermes.analytics.evaluation import (
    TradeEvaluation,
    label_paper_trade,
    compute_aggregate_metrics,
    OutcomeLabel,
)
from hermes.clock import trading_date_ist

logger = logging.getLogger(__name__)


def generate_strategy_report(trades: list[PaperTrade]) -> str:
    """Generate strategy-wise performance breakdown."""
    if not trades:
        return "### 🎯 Strategy Performance\nNo trades available."

    strategies: dict[str, list[PaperTrade]] = defaultdict(list)
    for t in trades:
        strategies[t.strategy or "ORB"].append(t)

    lines = [
        "### 🎯 Strategy Performance",
        "",
        "| Strategy | Trades | Wins | Win Rate | Net P&L | Avg P&L |",
        "|----------|--------|------|----------|---------|---------|",
    ]

    for strat_name in sorted(strategies.keys()):
        strat_trades = strategies[strat_name]
        count = len(strat_trades)
        wins = sum(1 for t in strat_trades if t.net_pnl > 0)
        wr = (wins / count) * 100 if count > 0 else 0.0
        net = sum(t.net_pnl for t in strat_trades)
        avg = net / count if count > 0 else 0.0
        lines.append(f"| {strat_name} | {count} | {wins} | {wr:.0f}% | ₹{net:+,.0f} | ₹{avg:+,.0f} |")

    return "\n".join(lines)


def generate_sector_report(trades: list[PaperTrade]) -> str:
    """Generate sector-wise performance breakdown."""
    if not trades:
        return "### 🏢 Sector Performance\nNo trades available."

    from hermes.domain.universe import SECTOR_MAP

    sectors: dict[str, list[PaperTrade]] = defaultdict(list)
    for t in trades:
        sector = SECTOR_MAP.get(t.symbol, "Other")
        sectors[sector].append(t)

    lines = [
        "### 🏢 Sector Performance",
        "",
        "| Sector | Trades | Win Rate | Net P&L |",
        "|--------|--------|----------|---------|",
    ]

    for sector_name in sorted(sectors.keys(), key=lambda s: -sum(t.net_pnl for t in sectors[s])):
        sec_trades = sectors[sector_name]
        count = len(sec_trades)
        wins = sum(1 for t in sec_trades if t.net_pnl > 0)
        wr = (wins / count) * 100 if count > 0 else 0.0
        net = sum(t.net_pnl for t in sec_trades)
        lines.append(f"| {sector_name} | {count} | {wr:.0f}% | ₹{net:+,.0f} |")

    return "\n".join(lines)


def generate_failure_tag_report(analyses: list[FailureAnalysis]) -> str:
    """Generate failure root-cause frequency report."""
    if not analyses:
        return "### 🔍 Failure Analysis\nNo failure analyses recorded."

    all_tags: list[str] = []
    for a in analyses:
        all_tags.extend(a.root_cause_tags)

    tag_counts = Counter(all_tags).most_common(10)

    lines = [
        "### 🔍 Top Failure Root Causes",
        "",
        "| Root Cause | Count | % of Failures |",
        "|------------|-------|---------------|",
    ]

    total = len(analyses)
    for tag, count in tag_counts:
        pct = (count / total) * 100 if total > 0 else 0.0
        lines.append(f"| {tag} | {count} | {pct:.0f}% |")

    return "\n".join(lines)


def generate_improvement_suggestions(
    trades: list[PaperTrade],
    analyses: list[FailureAnalysis],
) -> str:
    """Generate concrete improvement suggestions based on analytics data."""
    suggestions: list[str] = []

    if trades:
        wins = sum(1 for t in trades if t.net_pnl > 0)
        wr = (wins / len(trades)) * 100
        avg_loss = sum(t.net_pnl for t in trades if t.net_pnl < 0) / max(1, len(trades) - wins)

        if wr < 45:
            suggestions.append("📉 Win rate below 45% — consider tightening entry criteria or adding confirmation filters.")
        if avg_loss < -500:
            suggestions.append(f"💸 Average loss (₹{avg_loss:,.0f}) is high — review stop-loss placement and position sizing.")

        # Check for excessive time exits
        time_exits = sum(1 for t in trades if t.exit_reason in ("Time Exit", "EOD Close"))
        if time_exits > len(trades) * 0.5:
            suggestions.append("⏰ Over 50% of trades exit on time/EOD — targets may be too ambitious for session length.")

    if analyses:
        tag_counts = Counter(tag for a in analyses for tag in a.root_cause_tags)
        top_tag, top_count = tag_counts.most_common(1)[0] if tag_counts else ("", 0)
        if top_count >= 3:
            suggestions.append(f"🔁 Recurring failure: '{top_tag}' appeared {top_count} times — investigate and address systematically.")

    if not suggestions:
        suggestions.append("✅ No immediate improvements identified — continue monitoring.")

    lines = ["### 💡 Improvement Suggestions", ""]
    lines.extend(f"- {s}" for s in suggestions)
    return "\n".join(lines)


def generate_full_analytics_report(
    trades: list[PaperTrade],
    analyses: list[FailureAnalysis] | None = None,
) -> str:
    """Generate a comprehensive analytics report combining all sections."""
    sections = [
        generate_strategy_report(trades),
        generate_sector_report(trades),
    ]
    if analyses:
        sections.append(generate_failure_tag_report(analyses))
    sections.append(generate_improvement_suggestions(trades, analyses or []))

    return "\n\n---\n\n".join(sections)


def print_stats_summary() -> str:
    """Quick stats summary for /stats ChatOps command.

    Attempts to read from MongoDB; falls back to a placeholder
    if no connection is configured.
    """
    import os

    mongo_uri = os.getenv("MONGODB_URI")
    if not mongo_uri:
        msg = (
            "📈 **Analytics Summary**\n\n"
            "⚠️ MongoDB not configured (`MONGODB_URI` not set).\n"
            "Analytics data is only available when connected to MongoDB Atlas.\n"
            "Set `MONGODB_URI` in `.env` and re-run."
        )
        print(msg)
        return msg

    try:
        from analytics_mongo import MongoAnalyticsStore
        store = MongoAnalyticsStore(mongo_uri)
        today = trading_date_ist().strftime("%Y-%m-%d")

        trades_today = store.get_paper_trades(today)
        all_trades = store.get_paper_trades()

        today_count = len(trades_today)
        today_pnl = sum(t.net_pnl for t in trades_today)
        total_count = len(all_trades)
        total_pnl = sum(t.net_pnl for t in all_trades)
        total_wins = sum(1 for t in all_trades if t.net_pnl > 0)
        wr = (total_wins / total_count) * 100 if total_count > 0 else 0.0

        msg = (
            f"📈 **Analytics Summary**\n\n"
            f"**Today ({today}):** {today_count} trades | P&L: ₹{today_pnl:+,.0f}\n"
            f"**All Time:** {total_count} trades | Win Rate: {wr:.0f}% | Net P&L: ₹{total_pnl:+,.0f}\n"
        )
        print(msg)
        return msg

    except Exception as e:
        msg = f"📈 **Analytics Summary**\n\n⚠️ Error reading analytics: {e}"
        print(msg)
        return msg
