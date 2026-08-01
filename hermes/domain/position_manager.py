"""
Shared Position Manager state machine.
Evaluates intraday open position exits (SL, TP, Time Exit, EOD close) across paper, live, and backtesting.
"""

from dataclasses import dataclass
from datetime import time as dt_time
import logging
from hermes.domain.models import Candle

logger = logging.getLogger(__name__)


@dataclass
class PositionExitSignal:
    symbol: str
    exit_price: float
    exit_reason: str  # "SL Hit", "TP Hit", "Time Exit", "EOD Close"


class PositionManager:
    """Tracks active trades and checks candle price action against SL/TP boundaries."""

    def __init__(self, time_exit: dt_time = dt_time(15, 15), intrabar_mode: str = "pessimistic"):
        self.time_exit = time_exit
        self.intrabar_mode = intrabar_mode
        self.active_positions: dict[str, dict] = {}

    def track_position(self, symbol: str, side: str, entry_price: float, sl: float, tp: float) -> None:
        self.active_positions[symbol] = {
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "sl": sl,
            "tp": tp,
        }
        logger.info(f"PositionManager tracking {side} {symbol} | entry={entry_price:.2f} sl={sl:.2f} tp={tp:.2f}")

    def remove_position(self, symbol: str) -> None:
        self.active_positions.pop(symbol, None)

    def check_candle(self, candle: Candle, time_obj: dt_time) -> PositionExitSignal | None:
        pos = self.active_positions.get(candle.symbol)
        if not pos:
            return None

        is_long = (pos["side"] == "BUY" or pos["side"] == "LONG")
        sl_hit = (candle.low <= pos["sl"]) if is_long else (candle.high >= pos["sl"])
        tp_hit = (candle.high >= pos["tp"]) if is_long else (candle.low <= pos["tp"])

        exit_price: float | None = None
        exit_reason = ""

        if sl_hit and tp_hit:
            if self.intrabar_mode == "pessimistic":
                exit_price, exit_reason = pos["sl"], "SL Hit"
            else:
                exit_price, exit_reason = pos["tp"], "TP Hit"
        elif sl_hit:
            exit_price, exit_reason = pos["sl"], "SL Hit"
        elif tp_hit:
            exit_price, exit_reason = pos["tp"], "TP Hit"
        elif time_obj >= self.time_exit:
            exit_price, exit_reason = candle.close, "Time Exit"

        if exit_price is not None:
            return PositionExitSignal(
                symbol=candle.symbol,
                exit_price=exit_price,
                exit_reason=exit_reason,
            )

        return None
