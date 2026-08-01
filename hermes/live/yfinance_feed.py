"""
Yfinance-based market feed for paper trading without Dhan credentials.

Polls 1-minute bars for each symbol and pushes finalized candles into strategy
queues. Suitable for paper mode only — not for production latency requirements.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from queue import Full, Queue

import yfinance as yf

from hermes.clock import now_ist
from hermes.domain.models import Candle

logger = logging.getLogger(__name__)

MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)
POLL_INTERVAL_SECS = 55


class YfinanceFeedProducer:
    """Poll yfinance 1m bars and fan out candles to strategy queues."""

    def __init__(
        self,
        symbols: list[str],
        strategy_queues: list[Queue],
        *,
        poll_interval_secs: float = POLL_INTERVAL_SECS,
    ) -> None:
        self._symbols = symbols
        self._queues = strategy_queues
        self._poll_interval = poll_interval_secs
        self._is_running = False
        self._last_emitted: dict[str, str] = {}

    def start(self) -> None:
        """Blocking poll loop — run in the main thread."""
        self._is_running = True
        logger.info(
            "YfinanceFeedProducer started for %d symbols (paper mode, poll=%ds)",
            len(self._symbols),
            int(self._poll_interval),
        )

        while self._is_running:
            now = now_ist()
            if not self._in_market_hours(now):
                if now.hour < MARKET_OPEN[0] or (now.hour == MARKET_OPEN[0] and now.minute < MARKET_OPEN[1]):
                    logger.info("Pre-market — waiting for 09:15 IST …")
                else:
                    logger.info("Market closed — stopping yfinance feed.")
                    break
                time.sleep(30)
                continue

            for symbol in self._symbols:
                candle = self._fetch_latest_candle(symbol)
                if candle:
                    self._broadcast(candle)

            time.sleep(self._poll_interval)

        logger.info("YfinanceFeedProducer stopped.")

    def stop(self) -> None:
        self._is_running = False

    @staticmethod
    def _in_market_hours(now: datetime) -> bool:
        t = now.time()
        open_t = datetime.strptime("09:15", "%H:%M").time()
        close_t = datetime.strptime("15:30", "%H:%M").time()
        return open_t <= t <= close_t

    def _fetch_latest_candle(self, symbol: str) -> Candle | None:
        ticker = f"{symbol}.NS"
        try:
            df = yf.download(ticker, period="1d", interval="1m", progress=False)
            if df is None or df.empty:
                return None

            if hasattr(df.columns, "levels"):
                df = df.droplevel(1, axis=1) if df.columns.nlevels > 1 else df

            row = df.iloc[-1]
            ts = df.index[-1]
            if hasattr(ts, "tz_localize"):
                ts = ts.tz_localize(None) if ts.tzinfo else ts
            minute_str = ts.strftime("%Y-%m-%d %H:%M:00")

            if self._last_emitted.get(symbol) == minute_str:
                return None

            self._last_emitted[symbol] = minute_str
            return Candle(
                symbol=symbol,
                timestamp=minute_str,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=int(row.get("Volume", 0) or 0),
            )
        except Exception:
            logger.exception("Failed to fetch yfinance bar for %s", symbol)
            return None

    def _broadcast(self, candle: Candle) -> None:
        for q in self._queues:
            try:
                q.put(candle, block=False)
            except Full:
                logger.warning("Queue full — dropped candle for %s", candle.symbol)
