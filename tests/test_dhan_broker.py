"""Unit tests for DhanBroker stub."""

import pytest
from hermes.execution.dhan_broker import DhanBroker
from hermes.domain.orders import Order, OrderSide, OrderType


class TestDhanBrokerStub:
    def setup_method(self):
        self.broker = DhanBroker(client_id="test", access_token="test-token")

    def test_place_order_raises(self):
        order = Order(symbol="RELIANCE", security_id="11536", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10)
        with pytest.raises(NotImplementedError, match="place_order"):
            self.broker.place_order(order)

    def test_cancel_order_raises(self):
        with pytest.raises(NotImplementedError, match="cancel_order"):
            self.broker.cancel_order("ORD-123")

    def test_fetch_positions_raises(self):
        with pytest.raises(NotImplementedError, match="fetch_positions"):
            self.broker.fetch_positions()

    def test_fetch_orders_raises(self):
        with pytest.raises(NotImplementedError, match="fetch_orders"):
            self.broker.fetch_orders()

    def test_get_market_price_raises(self):
        with pytest.raises(NotImplementedError, match="get_market_price"):
            self.broker.get_market_price("RELIANCE")
