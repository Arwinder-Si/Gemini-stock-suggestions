"""
Strategy module — Opening Range Breakout (ORB).

The strategy class is intentionally decoupled from the global config
so it can be instantiated with different parameters for testing
and backtesting.

TODO: Add multi-strategy support — define a BaseStrategy ABC and have
      each strategy (ORB, VWAP crossover, etc.) subclass it.
TODO: Add risk controls — daily loss limits per symbol and portfolio-wide.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time as dt_time
from typing import Optional

from models import Candle, Signal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ORBConfig:
    """Plain container for strategy parameters — no global state."""
    orb_start: dt_time
    orb_end: dt_time
    min_volume: int
    rr_ratio: float
    exit_time: dt_time


class ORBBreakoutStrategy:
    """
    Opening Range Breakout strategy.

    Tracks the high/low during the ORB window, then emits a LONG or SHORT
    signal when a candle closes beyond that range with sufficient volume.

    Only one signal per symbol per day (no re-entry in v1).
    """

    def __init__(self, cfg: ORBConfig) -> None:
        self.cfg = cfg

        # Per-symbol, per-date state
        # Structure: { symbol: { "date": str, "orb_high": float, ... } }
        self._state: dict[str, dict] = {}

    # ── Public API ───────────────────────────────────────────────────

    def on_candle(self, candle: Candle) -> Optional[Signal]:
        """
        Processes a single candle and returns a Signal if criteria are met.
        Returns None otherwise.

        This method is used identically in both live mode and backtest mode.
        """
        try:
            dt = datetime.strptime(candle.timestamp, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            dt = datetime.fromisoformat(candle.timestamp)

        date_str = dt.strftime("%Y-%m-%d")
        time_obj = dt.time()
        symbol = candle.symbol

        # Ensure per-symbol state exists and is for the correct date
        self._ensure_state(symbol, date_str)
        state = self._state[symbol]

        # ── Inside the ORB window ────────────────────────────────────
        if self.cfg.orb_start <= time_obj <= self.cfg.orb_end:
            if state["orb_high"] is None:
                state["orb_high"] = candle.high
                state["orb_low"] = candle.low
            else:
                state["orb_high"] = max(state["orb_high"], candle.high)
                state["orb_low"] = min(state["orb_low"], candle.low)
            return None

        # ── Post ORB window ──────────────────────────────────────────
        if state["orb_high"] is None:
            # We missed the ORB window for this symbol today
            return None

        if time_obj >= self.cfg.exit_time:
            return None

        if state["signal_fired"]:
            return None

        orb_h = state["orb_high"]
        orb_l = state["orb_low"]
        signal: Signal | None = None

        # LONG breakout
        if candle.close > orb_h and candle.volume >= self.cfg.min_volume:
            entry = candle.close
            sl = orb_l
            risk = entry - sl
            tp = entry + (risk * self.cfg.rr_ratio)
            signal = Signal(
                symbol=symbol,
                timestamp=candle.timestamp,
                direction="LONG",
                entry=round(entry, 2),
                sl=round(sl, 2),
                tp=round(tp, 2),
                reason=(
                    f"Close {candle.close} > ORB High {orb_h} "
                    f"and Vol {candle.volume} >= {self.cfg.min_volume}"
                ),
            )

        # SHORT breakout
        elif candle.close < orb_l and candle.volume >= self.cfg.min_volume:
            entry = candle.close
            sl = orb_h
            risk = sl - entry
            tp = entry - (risk * self.cfg.rr_ratio)
            signal = Signal(
                symbol=symbol,
                timestamp=candle.timestamp,
                direction="SHORT",
                entry=round(entry, 2),
                sl=round(sl, 2),
                tp=round(tp, 2),
                reason=(
                    f"Close {candle.close} < ORB Low {orb_l} "
                    f"and Vol {candle.volume} >= {self.cfg.min_volume}"
                ),
            )

        if signal:
            state["signal_fired"] = True
            logger.info("Signal generated: %s %s on %s", signal.direction, symbol, signal.timestamp)
            return signal

        return None

    # ── Internals ────────────────────────────────────────────────────

    def _ensure_state(self, symbol: str, date_str: str) -> None:
        """Initialise or reset per-symbol state when the date changes."""
        if symbol not in self._state or self._state[symbol]["date"] != date_str:
            self._state[symbol] = {
                "date": date_str,
                "orb_high": None,
                "orb_low": None,
                "signal_fired": False,
            }
