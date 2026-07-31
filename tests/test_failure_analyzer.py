"""Unit tests for failure root-cause analyzer."""

from failure_analyzer import analyze_failure, POOR_SL_PLACEMENT, MARKET_REGIME_MISMATCH, HIGH_VOLATILITY, STRATEGY_FAILURE
from analytics_models import PaperTrade, Recommendation


class TestAnalyzeFailure:
    def test_profitable_trade_not_a_loss(self):
        trade = PaperTrade(trade_id="T1", net_pnl=100.0, entry_price=100.0, planned_sl=95.0)
        result = analyze_failure(trade)
        assert "NOT_A_LOSS" in result.root_cause_tags

    def test_tight_sl_detected(self):
        trade = PaperTrade(
            trade_id="T2", symbol="RELIANCE", net_pnl=-50.0,
            entry_price=2500.0, planned_sl=2494.0,
            exit_reason="SL Hit", stop_loss_hit=True,
        )
        result = analyze_failure(trade)
        assert POOR_SL_PLACEMENT in result.root_cause_tags

    def test_regime_mismatch_long_in_bear(self):
        trade = PaperTrade(
            trade_id="T3", symbol="TCS", net_pnl=-200.0,
            entry_price=4000.0, planned_sl=3950.0,
            exit_reason="SL Hit", stop_loss_hit=True,
        )
        rec = Recommendation(symbol="TCS", action="BUY")
        result = analyze_failure(trade, rec=rec, market_regime="BEAR")
        assert MARKET_REGIME_MISMATCH in result.root_cause_tags

    def test_high_volatility_tagged(self):
        trade = PaperTrade(
            trade_id="T4", symbol="INFY", net_pnl=-150.0,
            entry_price=1800.0, planned_sl=1780.0,
            exit_reason="SL Hit", stop_loss_hit=True,
        )
        result = analyze_failure(trade, vix_value=25.0)
        assert HIGH_VOLATILITY in result.root_cause_tags

    def test_time_exit_strategy_failure(self):
        trade = PaperTrade(
            trade_id="T5", symbol="HDFCBANK", net_pnl=-80.0,
            entry_price=1600.0, planned_sl=1580.0,
            exit_reason="Time Exit",
        )
        result = analyze_failure(trade)
        assert STRATEGY_FAILURE in result.root_cause_tags

    def test_context_snapshot_populated(self):
        trade = PaperTrade(
            trade_id="T6", symbol="WIPRO", net_pnl=-100.0,
            entry_price=500.0, planned_sl=490.0,
            exit_reason="SL Hit", stop_loss_hit=True,
        )
        rec = Recommendation(symbol="WIPRO", action="BUY", strategy="ORB", confidence_score=75.0)
        result = analyze_failure(trade, rec=rec, vix_value=15.0)
        assert result.context_snapshot["strategy"] == "ORB"
        assert result.context_snapshot["vix"] == 15.0
