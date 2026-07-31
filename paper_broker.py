"""
Paper Trading Execution Engine (Mock Broker).
Implements the Broker protocol to execute simulated orders against live LTP / feed ticks with CostModel charges.
"""

import logging
from broker import Broker
from orders import Order, OrderState, OrderSide
from costs import CostModel, Side
from portfolio import Portfolio
from clock import now_ist

logger = logging.getLogger(__name__)


class PaperBroker(Broker):
    """
    Mock broker executing orders in memory with realistic Indian slippage & cost modeling.
    """

    def __init__(self, portfolio: Portfolio, cost_model: CostModel | None = None):
        self.portfolio = portfolio
        self.cost_model = cost_model or CostModel()
        self.orders: dict[str, Order] = {}  # client_order_id -> Order
        self.latest_ltps: dict[str, float] = {}

    def update_market_price(self, symbol: str, ltp: float) -> None:
        """Update last traded price for symbol."""
        self.latest_ltps[symbol] = ltp

    def get_market_price(self, symbol: str) -> float:
        return self.latest_ltps.get(symbol, 0.0)

    def place_order(self, order: Order) -> Order:
        """Execute simulated market order."""
        ltp = self.get_market_price(order.symbol)
        if ltp <= 0.0:
            ltp = order.price if order.price > 0 else 100.0

        side = Side.BUY if order.side == OrderSide.BUY else Side.SELL
        fill_price = self.cost_model.apply_slippage(ltp, side, is_entry=True)

        charge_breakdown = self.cost_model.charges(fill_price, order.quantity, side)

        # Check portfolio cash for BUY orders
        if order.side == OrderSide.BUY and self.portfolio.available_cash < charge_breakdown.net_amount:
            order.state = OrderState.REJECTED
            order.rejection_reason = f"Insufficient cash: Required ₹{charge_breakdown.net_amount:.2f}, Available ₹{self.portfolio.available_cash:.2f}"
            logger.warning(f"PaperBroker REJECTED order {order.client_order_id}: {order.rejection_reason}")
            self.orders[order.client_order_id] = order
            return order

        # Fill order
        order.state = OrderState.FILLED
        order.filled_quantity = order.quantity
        order.average_fill_price = fill_price
        order.broker_order_id = f"MOCK-{now_ist().strftime('%H%M%S%f')[:10]}"
        order.updated_at = now_ist().strftime("%Y-%m-%d %H:%M:%S IST")

        # Record in portfolio if opening position
        if order.side == OrderSide.BUY:
            self.portfolio.open_position(
                symbol=order.symbol,
                side="BUY",
                qty=order.quantity,
                entry_price=fill_price,
                net_amount=charge_breakdown.net_amount,
            )

        self.orders[order.client_order_id] = order
        logger.info(f"PaperBroker FILLED {order.side} {order.symbol} x{order.quantity} @ ₹{fill_price:.2f} (Order ID: {order.client_order_id})")
        return order

    def cancel_order(self, client_order_id: str) -> bool:
        order = self.orders.get(client_order_id)
        if not order or order.state in (OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED):
            return False

        order.state = OrderState.CANCELLED
        order.updated_at = now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
        return True

    def fetch_positions(self) -> list[dict]:
        return list(self.portfolio.positions.values())

    def fetch_orders(self) -> list[Order]:
        return list(self.orders.values())
