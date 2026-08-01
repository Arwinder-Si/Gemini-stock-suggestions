"""
Market Snapshot Job — captures daily benchmark data after market close.

Collects top gainers/losers from universe, index performance (Nifty 50,
Bank Nifty, India VIX), and sector-wise performance for comparison with
agent recommendations.

Usage:
    python market_snapshot_job.py           # Run for today
    python market_snapshot_job.py 2026-08-01  # Run for specific date
"""

from __future__ import annotations

import sys
import logging
from dataclasses import dataclass, field

from hermes.clock import trading_date_ist, now_ist

logger = logging.getLogger(__name__)


@dataclass
class MarketSnapshot:
    """Daily market benchmark document."""
    trading_date: str = ""
    timestamp: str = field(default_factory=lambda: now_ist().strftime("%Y-%m-%d %H:%M:%S IST"))
    nifty50_close: float = 0.0
    nifty50_change_pct: float = 0.0
    banknifty_close: float = 0.0
    banknifty_change_pct: float = 0.0
    india_vix: float = 0.0
    top_gainers: list[dict] = field(default_factory=list)   # [{symbol, change_pct}]
    top_losers: list[dict] = field(default_factory=list)    # [{symbol, change_pct}]
    sector_performance: dict[str, float] = field(default_factory=dict)  # {sector: avg_return_pct}
    advance_count: int = 0
    decline_count: int = 0
    market_breadth: str = ""  # "BULLISH", "BEARISH", "NEUTRAL"


def build_market_snapshot(trading_date_str: str | None = None) -> MarketSnapshot:
    """Build a daily market snapshot from yfinance data.

    Downloads EOD data for indices and universe stocks.
    Designed to run post-session (after 3:45 PM IST).
    """
    import yfinance as yf
    from hermes.domain.universe import NIFTY_LARGE, SECTOR_MAP

    date_str = trading_date_str or trading_date_ist().strftime("%Y-%m-%d")
    snapshot = MarketSnapshot(trading_date=date_str)

    # 1. Index performance
    try:
        indices = yf.download(
            ["^NSEI", "^NSEBANK", "^INDIAVIX"],
            period="5d",
            interval="1d",
            progress=False,
        )
        if not indices.empty:
            # Nifty 50
            if "^NSEI" in str(indices.columns):
                nifty = indices["Close"]["^NSEI"].dropna()
                if len(nifty) >= 2:
                    snapshot.nifty50_close = round(float(nifty.iloc[-1]), 2)
                    snapshot.nifty50_change_pct = round(
                        ((nifty.iloc[-1] - nifty.iloc[-2]) / nifty.iloc[-2]) * 100, 2
                    )

            # Bank Nifty
            if "^NSEBANK" in str(indices.columns):
                bank = indices["Close"]["^NSEBANK"].dropna()
                if len(bank) >= 2:
                    snapshot.banknifty_close = round(float(bank.iloc[-1]), 2)
                    snapshot.banknifty_change_pct = round(
                        ((bank.iloc[-1] - bank.iloc[-2]) / bank.iloc[-2]) * 100, 2
                    )

            # India VIX
            if "^INDIAVIX" in str(indices.columns):
                vix = indices["Close"]["^INDIAVIX"].dropna()
                if len(vix) >= 1:
                    snapshot.india_vix = round(float(vix.iloc[-1]), 2)
    except Exception as e:
        logger.warning(f"Failed to fetch index data: {e}")

    # 2. Universe stock performance
    try:
        tickers = [f"{t}.NS" for t in NIFTY_LARGE[:50]]  # Top 50 for speed
        data = yf.download(tickers, period="5d", interval="1d", progress=False)

        if not data.empty and "Close" in data.columns.get_level_values(0):
            close = data["Close"].dropna(how="all")
            if len(close) >= 2:
                last = close.iloc[-1]
                prev = close.iloc[-2]
                returns = ((last - prev) / prev * 100).dropna()

                # Clean ticker names (remove .NS)
                returns.index = [t.replace(".NS", "") for t in returns.index]

                # Top gainers/losers
                sorted_ret = returns.sort_values(ascending=False)
                snapshot.top_gainers = [
                    {"symbol": sym, "change_pct": round(float(ret), 2)}
                    for sym, ret in sorted_ret.head(5).items()
                ]
                snapshot.top_losers = [
                    {"symbol": sym, "change_pct": round(float(ret), 2)}
                    for sym, ret in sorted_ret.tail(5).items()
                ]

                # Advance/Decline
                snapshot.advance_count = int((returns > 0).sum())
                snapshot.decline_count = int((returns <= 0).sum())
                total = snapshot.advance_count + snapshot.decline_count
                if total > 0:
                    ratio = snapshot.advance_count / total
                    if ratio > 0.6:
                        snapshot.market_breadth = "BULLISH"
                    elif ratio < 0.4:
                        snapshot.market_breadth = "BEARISH"
                    else:
                        snapshot.market_breadth = "NEUTRAL"

                # Sector-wise performance
                sector_returns: dict[str, list[float]] = {}
                for sym, ret in returns.items():
                    sector = SECTOR_MAP.get(sym, "Other")
                    sector_returns.setdefault(sector, []).append(float(ret))
                snapshot.sector_performance = {
                    sector: round(sum(rets) / len(rets), 2)
                    for sector, rets in sorted(sector_returns.items(), key=lambda x: -sum(x[1]) / len(x[1]))
                }
    except Exception as e:
        logger.warning(f"Failed to fetch universe data: {e}")

    return snapshot


def main() -> None:
    """CLI entry point for market snapshot job."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    snapshot = build_market_snapshot(date_str)

    print(f"\n📊 Market Snapshot for {snapshot.trading_date}")
    print(f"   Nifty 50: {snapshot.nifty50_close:,.2f} ({snapshot.nifty50_change_pct:+.2f}%)")
    print(f"   Bank Nifty: {snapshot.banknifty_close:,.2f} ({snapshot.banknifty_change_pct:+.2f}%)")
    print(f"   India VIX: {snapshot.india_vix:.2f}")
    print(f"   Breadth: {snapshot.market_breadth} (A:{snapshot.advance_count} / D:{snapshot.decline_count})")

    if snapshot.top_gainers:
        print(f"\n   Top Gainers:")
        for g in snapshot.top_gainers:
            print(f"     {g['symbol']}: {g['change_pct']:+.2f}%")

    if snapshot.top_losers:
        print(f"\n   Top Losers:")
        for l in snapshot.top_losers:
            print(f"     {l['symbol']}: {l['change_pct']:+.2f}%")

    if snapshot.sector_performance:
        print(f"\n   Sector Performance:")
        for sector, ret in snapshot.sector_performance.items():
            print(f"     {sector}: {ret:+.2f}%")


if __name__ == "__main__":
    main()
