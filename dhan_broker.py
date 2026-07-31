"""
Dhan Broker — stub implementation of the Broker protocol.

Placeholder for Phase 4 live execution. All methods raise
NotImplementedError until the Dhan Order API is integrated.
"""

from __future__ import annotations

from broker import Broker
from orders import Order


class DhanBroker:
    """Stub broker for Phase 4 live execution via Dhan Order API.

    Implements the ``Broker`` protocol interface but raises
    ``NotImplementedError`` on every method until the real
    integration is built (pending SEBI compliance confirmation).
    """

    def __init__(self, client_id: str, access_token: str) -> None:
        self._client_id = client_id
        self._access_token = access_token

    def place_order(self, order: Order) -> Order:
        raise NotImplementedError("DhanBroker.place_order is not yet implemented. Use PaperBroker for testing.")

    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError("DhanBroker.cancel_order is not yet implemented.")

    def fetch_positions(self) -> list[dict]:
        raise NotImplementedError("DhanBroker.fetch_positions is not yet implemented.")

    def fetch_orders(self) -> list[Order]:
        raise NotImplementedError("DhanBroker.fetch_orders is not yet implemented.")

    def get_market_price(self, symbol: str) -> float:
        raise NotImplementedError("DhanBroker.get_market_price is not yet implemented.")
