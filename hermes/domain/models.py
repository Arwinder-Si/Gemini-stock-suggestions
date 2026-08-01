from dataclasses import dataclass
from typing import Literal

@dataclass
class Candle:
    symbol: str
    timestamp: str  # Format: YYYY-MM-DD HH:MM:SS
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class Signal:
    symbol: str
    timestamp: str  # Format: YYYY-MM-DD HH:MM:SS
    direction: Literal["LONG", "SHORT", "UPDATE_SL", "EXIT"]
    entry: float
    sl: float
    tp: float
    reason: str
    pnl_pct: float = 0.0  # Used for EXIT signals to log final PnL
