"""
Abstract Broker Protocol interface.
Allows paper trading engine and live Dhan broker implementations to be swapped transparently.
"""

from typing import Protocol, runtime_checkable
from hermes.domain.orders import Order


@runtime_checkable
class Broker(Protocol):
    """Protocol establishing the required interface for execution engines."""

    def place_order(self, order: Order) -> Order:
        """Submit an order for execution. Returns updated Order object."""
        ...

    def cancel_order(self, client_order_id: str) -> bool:
        """Cancel an existing active order by client_order_id."""
        ...

    def fetch_positions(self) -> list[dict]:
        """Fetch current open positions."""
        ...

    def fetch_orders(self) -> list[Order]:
        """Fetch list of all orders for the current session."""
        ...

    def get_market_price(self, symbol: str) -> float:
        """Get latest market price (LTP) for symbol."""
        ...
