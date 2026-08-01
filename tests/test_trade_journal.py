import pytest
from hermes.data.analytics_models import Recommendation, PaperTrade
from hermes.analytics.trade_journal import build_trade_journal_entry

def test_build_trade_journal_entry():
    rec = Recommendation(
        recommendation_id="REC-123",
        symbol="RELIANCE",
        sector="Energy",
        reasoning="ORB Breakout above 2500",
        stop_loss=2480.0,
        target_price=2540.0,
    )

    trade = PaperTrade(
        trade_id="TRD-456",
        recommendation_id="REC-123",
        trading_date="2026-07-31",
        symbol="RELIANCE",
        side="BUY",
        quantity=100,
        entry_time="2026-07-31 09:35:00 IST",
        entry_price=2500.0,
        exit_time="2026-07-31 10:15:00 IST",
        exit_price=2540.0,
        exit_reason="TP Hit",
        gross_pnl=4000.0,
        total_charges=75.0,
        net_pnl=3925.0,
        return_pct=1.57,
    )

    entry = build_trade_journal_entry(rec, trade)

    assert entry.trade_id == "TRD-456"
    assert entry.symbol == "RELIANCE"
    assert entry.is_win is True
    assert entry.target_hit is True
    assert entry.stop_loss_hit is False
    assert entry.holding_duration_mins == 40
    assert entry.net_pnl == 3925.0
    assert entry.stt > 0.0
