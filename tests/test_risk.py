import pytest
from risk import RiskEngine, RiskConfig
from analytics_models import Recommendation

def test_risk_engine_checks():
    cfg = RiskConfig(max_daily_trades=2, max_daily_loss_rupees=5000.0)
    re = RiskEngine(cfg)

    rec = Recommendation(
        symbol="RELIANCE",
        entry_price=2500.0,
        stop_loss=2480.0,  # ₹20 risk per share
        sector="Energy",
    )

    # Test valid recommendation -> 1% of ₹1,000,000 portfolio = ₹10,000 risk capital / ₹20 risk = 500 shares
    passed, reason, qty = re.validate_recommendation(
        rec=rec,
        current_daily_trades=0,
        realized_pnl_today=0.0,
        portfolio_value=1_000_000.0,
        open_positions=[],
        completed_symbols_today=set(),
    )
    assert passed is True
    assert qty == 500

    # Test max daily trades breach
    passed, reason, qty = re.validate_recommendation(
        rec=rec,
        current_daily_trades=2,
        realized_pnl_today=0.0,
        portfolio_value=1_000_000.0,
        open_positions=[],
        completed_symbols_today=set(),
    )
    assert passed is False
    assert "Max daily trade count" in reason

    # Test max daily loss breach
    passed, reason, qty = re.validate_recommendation(
        rec=rec,
        current_daily_trades=0,
        realized_pnl_today=-6000.0,
        portfolio_value=1_000_000.0,
        open_positions=[],
        completed_symbols_today=set(),
    )
    assert passed is False
    assert "Max daily loss limit breached" in reason

    # Test duplicate symbol block
    passed, reason, qty = re.validate_recommendation(
        rec=rec,
        current_daily_trades=0,
        realized_pnl_today=0.0,
        portfolio_value=1_000_000.0,
        open_positions=[{"symbol": "RELIANCE", "sector": "Energy", "value": 100000}],
        completed_symbols_today=set(),
    )
    assert passed is False
    assert "Position already exists" in reason
