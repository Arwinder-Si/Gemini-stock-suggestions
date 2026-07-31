import pytest
from orders import Order, OrderSide, OrderType, OrderState
from portfolio import Portfolio
from paper_broker import PaperBroker
from costs import CostModel

def test_paper_broker_fill_order():
    port = Portfolio(starting_capital=500_000.0)
    cm = CostModel(slippage_bps=5.0)
    pb = PaperBroker(portfolio=port, cost_model=cm)

    pb.update_market_price("RELIANCE", 2500.0)

    order = Order(
        symbol="RELIANCE",
        security_id="11536",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=100,
    )

    res_order = pb.place_order(order)
    assert res_order.state == OrderState.FILLED
    assert res_order.filled_quantity == 100
    assert res_order.average_fill_price > 2500.0  # Slippage applied
    assert len(port.positions) == 1
    assert port.available_cash < 500_000.0

def test_paper_broker_insufficient_cash():
    port = Portfolio(starting_capital=100.0)  # Low cash
    pb = PaperBroker(portfolio=port)
    pb.update_market_price("RELIANCE", 2500.0)

    order = Order(
        symbol="RELIANCE",
        security_id="11536",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=100,
    )

    res_order = pb.place_order(order)
    assert res_order.state == OrderState.REJECTED
    assert "Insufficient cash" in res_order.rejection_reason
