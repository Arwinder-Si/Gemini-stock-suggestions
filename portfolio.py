"""
Virtual Portfolio state management for Paper Trading.
"""

import logging
from analytics_models import PortfolioSnapshot
from clock import now_ist, trading_date_ist

logger = logging.getLogger(__name__)


class Portfolio:
    """Manages virtual account balances, cash, mark-to-market valuations, and positions."""

    def __init__(self, starting_capital: float = 1_000_000.0):
        self.starting_capital = starting_capital
        self.available_cash = starting_capital
        self.positions: dict[str, dict] = {}  # symbol -> position dict
        self.completed_trades_today: list[dict] = []
        self.completed_symbols_today: set[str] = set()

    @property
    def capital_deployed(self) -> float:
        return sum(pos["quantity"] * pos["entry_price"] for pos in self.positions.values())

    @property
    def realized_pnl_today(self) -> float:
        return sum(trade["net_pnl"] for trade in self.completed_trades_today)

    def get_unrealized_pnl(self, current_ltps: dict[str, float]) -> float:
        total_mtm = 0.0
        for sym, pos in self.positions.items():
            ltp = current_ltps.get(sym, pos["entry_price"])
            if pos["side"] == "BUY":
                total_mtm += (ltp - pos["entry_price"]) * pos["quantity"]
            else:
                total_mtm += (pos["entry_price"] - ltp) * pos["quantity"]
        return total_mtm

    def get_total_portfolio_value(self, current_ltps: dict[str, float]) -> float:
        return self.available_cash + self.capital_deployed + self.get_unrealized_pnl(current_ltps)

    def open_position(self, symbol: str, side: str, qty: int, entry_price: float, net_amount: float, sector: str = "Other") -> None:
        self.positions[symbol] = {
            "symbol": symbol,
            "side": side,
            "quantity": qty,
            "entry_price": entry_price,
            "sector": sector,
            "value": entry_price * qty,
        }
        # Debit or adjust available cash
        self.available_cash -= net_amount
        logger.info(f"Portfolio OPENED {side} {symbol} x{qty} @ ₹{entry_price:.2f}. Cash remaining: ₹{self.available_cash:.2f}")

    def close_position(self, symbol: str, exit_price: float, net_pnl: float, net_amount: float) -> dict | None:
        pos = self.positions.pop(symbol, None)
        if not pos:
            return None

        self.available_cash += net_amount
        trade_record = {
            "symbol": symbol,
            "side": pos["side"],
            "quantity": pos["quantity"],
            "entry_price": pos["entry_price"],
            "exit_price": exit_price,
            "net_pnl": net_pnl,
        }
        self.completed_trades_today.append(trade_record)
        self.completed_symbols_today.add(symbol)

        logger.info(f"Portfolio CLOSED {symbol} @ ₹{exit_price:.2f}. Net PnL: ₹{net_pnl:.2f}. Available cash: ₹{self.available_cash:.2f}")
        return trade_record

    def get_snapshot(self, current_ltps: dict[str, float]) -> PortfolioSnapshot:
        today_str = trading_date_ist().strftime("%Y-%m-%d")
        unrealized = self.get_unrealized_pnl(current_ltps)

        return PortfolioSnapshot(
            trading_date=today_str,
            starting_capital=self.starting_capital,
            available_cash=self.available_cash,
            capital_deployed=self.capital_deployed,
            realized_pnl_today=self.realized_pnl_today,
            unrealized_pnl_today=unrealized,
            total_net_pnl_cumulative=self.realized_pnl_today,
            total_trades_today=len(self.completed_trades_today),
            open_positions_count=len(self.positions),
        )
