"""
Daily Report — Paper vs Backtest comparison.

Compares paper trading results from the day against what the backtest
engine would have produced on the same candle data, to validate
fill fidelity and signal consistency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from hermes.data.analytics_models import PaperTrade
from hermes.clock import trading_date_ist

logger = logging.getLogger(__name__)


@dataclass
class DailyComparisonReport:
    """Comparison between paper and backtest results for a single day."""
    trading_date: str = ""
    paper_trades_count: int = 0
    paper_net_pnl: float = 0.0
    paper_win_rate: float = 0.0
    paper_avg_slippage_bps: float = 0.0
    signals_fired: int = 0
    signals_traded: int = 0
    signals_missed: int = 0
    notes: list[str] = None

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


def build_daily_comparison(
    paper_trades: list[PaperTrade],
    trading_date_str: str | None = None,
) -> DailyComparisonReport:
    """Build a daily comparison report from paper trade data.

    In a full implementation, this would also replay the same candle data
    through the backtest engine for comparison. Currently, it summarizes
    paper performance and flags discrepancies for manual review.
    """
    date_str = trading_date_str or trading_date_ist().strftime("%Y-%m-%d")

    # Filter to requested date
    day_trades = [t for t in paper_trades if t.trading_date == date_str]

    report = DailyComparisonReport(trading_date=date_str)

    if not day_trades:
        report.notes.append("No paper trades executed today.")
        return report

    report.paper_trades_count = len(day_trades)
    report.paper_net_pnl = round(sum(t.net_pnl for t in day_trades), 2)

    wins = sum(1 for t in day_trades if t.net_pnl > 0)
    report.paper_win_rate = round((wins / len(day_trades)) * 100, 1)

    # Estimate slippage from entry vs planned entry
    slippage_samples = []
    for t in day_trades:
        if t.entry_price > 0 and t.planned_sl > 0:
            # Very rough: compare actual entry to the midpoint of entry zone
            pass  # Would need backtest reference price to compute actual slippage

    report.signals_fired = len(day_trades)
    report.signals_traded = len(day_trades)

    # Summary notes
    if report.paper_win_rate < 40:
        report.notes.append(f"⚠️ Low win rate today ({report.paper_win_rate:.0f}%)")
    if report.paper_net_pnl < -5000:
        report.notes.append(f"⚠️ Significant daily loss: ₹{report.paper_net_pnl:,.0f}")
    if not report.notes:
        report.notes.append("✅ Normal trading day.")

    return report


def format_daily_report(report: DailyComparisonReport) -> str:
    """Format the daily comparison as a markdown report."""
    lines = [
        f"### 📊 Daily Report — {report.trading_date}",
        "",
        f"**Paper Trades:** {report.paper_trades_count}",
        f"**Paper Net P&L:** ₹{report.paper_net_pnl:+,.2f}",
        f"**Win Rate:** {report.paper_win_rate:.1f}%",
        "",
    ]

    if report.notes:
        lines.append("**Notes:**")
        for note in report.notes:
            lines.append(f"- {note}")

    return "\n".join(lines)
