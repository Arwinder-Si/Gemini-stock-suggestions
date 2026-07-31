import pytest
from costs import CostModel, Side, ChargeBreakdown

def test_cost_model_buy_side():
    cm = CostModel(slippage_bps=0)  # No slippage to test exact statutory charges
    ch = cm.charges(price=1000.0, qty=100, side=Side.BUY)

    assert ch.turnover == 100000.0
    # Brokerage: min(20, 100000 * 0.0003 = 30) => 20.0
    assert ch.brokerage == 20.0
    # STT: 0 on buy for intraday equity
    assert ch.stt == 0.0
    # Exchange txn: 100000 * 0.0000345 = 3.45
    assert ch.exchange_txn_charge == 3.45
    # GST: 18% of (20 + 3.45) = 4.221 => 4.22
    assert ch.gst == 4.22
    # Stamp duty: 100000 * 0.00003 = 3.0
    assert ch.stamp_duty == 3.0
    # Net amount: turnover + charges
    assert ch.net_amount > ch.turnover

def test_cost_model_sell_side():
    cm = CostModel(slippage_bps=0)
    ch = cm.charges(price=1000.0, qty=100, side=Side.SELL)

    # STT on sell side: 100000 * 0.00025 = 25.0
    assert ch.stt == 25.0
    # Stamp duty: 0 on sell side
    assert ch.stamp_duty == 0.0

def test_round_trip_pnl():
    cm = CostModel(slippage_bps=5)
    entry_ch, exit_ch, gross_pnl, net_pnl = cm.round_trip(100.0, 105.0, 100, Side.BUY)
    
    assert gross_pnl == 500.0
    assert net_pnl < gross_pnl

def test_apply_slippage():
    cm = CostModel(slippage_bps=10) # 0.1%
    buy_order = cm.apply_slippage(100.0, Side.BUY)
    assert buy_order == 100.10

    sell_order = cm.apply_slippage(100.0, Side.SELL)
    assert sell_order == 99.90
