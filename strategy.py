"""
Strategy module — Opening Range Breakout (ORB).

The strategy class is intentionally decoupled from the global config
so it can be instantiated with different parameters for testing
and backtesting.
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
    Opening Range Breakout strategy with VWAP filter and Trade Management.

    Tracks the high/low during the ORB window, then emits a LONG or SHORT
    signal when a candle closes beyond that range with sufficient volume AND VWAP confirmation.

    Manages active trades by emitting UPDATE_SL and EXIT signals.
    """

    def __init__(self, cfg: ORBConfig) -> None:
        self.cfg = cfg
        self._state: dict[str, dict] = {}

    def on_candle(self, candle: Candle) -> Optional[Signal]:
        try:
            dt = datetime.strptime(candle.timestamp, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            dt = datetime.fromisoformat(candle.timestamp)

        date_str = dt.strftime("%Y-%m-%d")
        time_obj = dt.time()
        symbol = candle.symbol

        self._ensure_state(symbol, date_str)
        state = self._state[symbol]

        # ── Calculate intraday VWAP ──
        typ_price = (candle.high + candle.low + candle.close) / 3
        state["cum_vol"] += candle.volume
        state["cum_typ_price_vol"] += typ_price * candle.volume
        if state["cum_vol"] > 0:
            state["vwap"] = state["cum_typ_price_vol"] / state["cum_vol"]
            
        if state["daily_open"] is None:
            state["daily_open"] = candle.open

        # ── Inside the ORB window ──
        if self.cfg.orb_start <= time_obj <= self.cfg.orb_end:
            if state["orb_high"] is None:
                state["orb_high"] = candle.high
                state["orb_low"] = candle.low
            else:
                state["orb_high"] = max(state["orb_high"], candle.high)
                state["orb_low"] = min(state["orb_low"], candle.low)
            return None

        if state["orb_high"] is None:
            return None

        # ── Time-based Exit for Active Trades ──
        if time_obj >= self.cfg.exit_time:
            if state["active_trade"]:
                pnl = (candle.close / state["entry"] - 1) * 100 if state["active_trade"] == "LONG" else (state["entry"] / candle.close - 1) * 100
                sig = Signal(symbol=symbol, timestamp=candle.timestamp, direction="EXIT",
                             entry=state["entry"], sl=state["sl"], tp=state["tp"],
                             reason="End of day forced exit", pnl_pct=round(pnl, 2))
                state["active_trade"] = None
                return sig
            return None

        # ── Trade Management (Active Trades) ──
        if state["active_trade"]:
            entry = state["entry"]
            sl = state["sl"]
            tp = state["tp"]
            direction = state["active_trade"]
            
            # Check Stop Loss
            if (direction == "LONG" and candle.close <= sl) or (direction == "SHORT" and candle.close >= sl):
                pnl = (sl / entry - 1) * 100 if direction == "LONG" else (entry / sl - 1) * 100
                sig = Signal(symbol=symbol, timestamp=candle.timestamp, direction="EXIT",
                             entry=entry, sl=sl, tp=tp,
                             reason=f"Stop Loss hit at {sl}", pnl_pct=round(pnl, 2))
                state["active_trade"] = None
                return sig
                
            # Check Take Profit
            if (direction == "LONG" and candle.close >= tp) or (direction == "SHORT" and candle.close <= tp):
                pnl = (tp / entry - 1) * 100 if direction == "LONG" else (entry / tp - 1) * 100
                sig = Signal(symbol=symbol, timestamp=candle.timestamp, direction="EXIT",
                             entry=entry, sl=sl, tp=tp,
                             reason=f"Take Profit hit at {tp}", pnl_pct=round(pnl, 2))
                state["active_trade"] = None
                return sig
                
            # Trailing Stop to Breakeven (at 1R)
            if direction == "LONG" and state["original_sl"] < entry:
                risk = entry - state["original_sl"]
                if candle.close >= entry + risk and sl < entry:
                    state["sl"] = entry
                    return Signal(symbol=symbol, timestamp=candle.timestamp, direction="UPDATE_SL",
                                  entry=entry, sl=entry, tp=tp, reason="Price reached 1R; trailing SL to breakeven")
            elif direction == "SHORT" and state["original_sl"] > entry:
                risk = state["original_sl"] - entry
                if candle.close <= entry - risk and sl > entry:
                    state["sl"] = entry
                    return Signal(symbol=symbol, timestamp=candle.timestamp, direction="UPDATE_SL",
                                  entry=entry, sl=entry, tp=tp, reason="Price reached 1R; trailing SL to breakeven")
                                  
            return None

        # ── Entry Logic (No Active Trade) ──
        if state["signal_fired"]:
            return None

        orb_h = state["orb_high"]
        orb_l = state["orb_low"]
        vwap = state["vwap"]
        signal: Signal | None = None

        # LONG breakout
        if candle.close > orb_h and candle.volume >= self.cfg.min_volume and candle.close > vwap:
            day_gain = ((candle.close / state["daily_open"]) - 1) * 100 if state["daily_open"] else 0
            if day_gain > 8.0:
                logger.warning(f"Rejected LONG on {symbol}: price already up {day_gain:.1f}% (Near Upper Circuit limit).")
                return None
                
            entry = candle.close
            sl = orb_l
            risk = entry - sl
            tp = entry + (risk * self.cfg.rr_ratio)
            signal = Signal(
                symbol=symbol, timestamp=candle.timestamp, direction="LONG",
                entry=round(entry, 2), sl=round(sl, 2), tp=round(tp, 2),
                reason=f"Close > ORB High and VWAP with Vol >= {self.cfg.min_volume}",
            )
            state["active_trade"] = "LONG"

        # SHORT breakout
        elif candle.close < orb_l and candle.volume >= self.cfg.min_volume and candle.close < vwap:
            entry = candle.close
            sl = orb_h
            risk = sl - entry
            tp = entry - (risk * self.cfg.rr_ratio)
            signal = Signal(
                symbol=symbol, timestamp=candle.timestamp, direction="SHORT",
                entry=round(entry, 2), sl=round(sl, 2), tp=round(tp, 2),
                reason=f"Close < ORB Low and VWAP with Vol >= {self.cfg.min_volume}",
            )
            state["active_trade"] = "SHORT"

        if signal:
            state["signal_fired"] = True
            state["entry"] = signal.entry
            state["sl"] = signal.sl
            state["original_sl"] = signal.sl
            state["tp"] = signal.tp
            logger.info("Signal generated: %s %s on %s", signal.direction, symbol, signal.timestamp)
            return signal

        return None

    def _ensure_state(self, symbol: str, date_str: str) -> None:
        if symbol not in self._state or self._state[symbol]["date"] != date_str:
            self._state[symbol] = {
                "date": date_str,
                "daily_open": None,
                "orb_high": None,
                "orb_low": None,
                "signal_fired": False,
                "active_trade": None,
                "entry": 0.0,
                "sl": 0.0,
                "original_sl": 0.0,
                "tp": 0.0,
                "cum_vol": 0,
                "cum_typ_price_vol": 0.0,
                "vwap": 0.0
            }
