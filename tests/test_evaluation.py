"""Unit tests for rule-based trade evaluation."""

from hermes.analytics.evaluation import (
    label_paper_trade,
    label_recommendation_outcome,
    compute_aggregate_metrics,
    OutcomeLabel,
    TradeEvaluation,
)
from hermes.data.analytics_models import PaperTrade, Recommendation
from hermes.pipelines.steps.outcome_enricher import RecommendationOutcome


class TestLabelPaperTrade:
    def test_successful_tp_hit(self):
        trade = PaperTrade(
            trade_id="T1", symbol="RELIANCE", net_pnl=500.0,
            target_hit=True, stop_loss_hit=False, exit_reason="TP Hit",
        )
        ev = label_paper_trade(trade)
        assert ev.outcome_label == OutcomeLabel.SUCCESSFUL.value

    def test_partially_successful(self):
        trade = PaperTrade(
            trade_id="T2", symbol="TCS", net_pnl=100.0,
            target_hit=False, stop_loss_hit=False, exit_reason="Time Exit",
        )
        ev = label_paper_trade(trade)
        assert ev.outcome_label == OutcomeLabel.PARTIALLY_SUCCESSFUL.value

    def test_failed_sl_hit(self):
        trade = PaperTrade(
            trade_id="T3", symbol="INFY", net_pnl=-300.0,
            target_hit=False, stop_loss_hit=True, exit_reason="SL Hit",
        )
        ev = label_paper_trade(trade)
        assert ev.outcome_label == OutcomeLabel.FAILED.value

    def test_failed_negative_pnl(self):
        trade = PaperTrade(
            trade_id="T4", symbol="HDFCBANK", net_pnl=-50.0,
            target_hit=False, stop_loss_hit=False, exit_reason="EOD Close",
        )
        ev = label_paper_trade(trade)
        assert ev.outcome_label == OutcomeLabel.FAILED.value


class TestLabelRecommendationOutcome:
    def test_target_hit_successful(self):
        rec = Recommendation(symbol="RELIANCE", action="BUY", entry_price=2500, target_price=2600)
        outcome = RecommendationOutcome(
            recommendation_id="R1", symbol="RELIANCE", trading_date="2026-08-01",
            actual_entry_price=2500, highest_price_reached=2650,
            lowest_price_reached=2480, closing_price=2620,
            max_gain_pct=6.0, max_drawdown_pct=-0.8,
            target_hit=True, stop_loss_hit=False, final_pnl_pct=4.8,
        )
        ev = label_recommendation_outcome(rec, outcome)
        assert ev.outcome_label == OutcomeLabel.SUCCESSFUL.value

    def test_false_positive(self):
        rec = Recommendation(symbol="TCS", action="BUY", entry_price=4000)
        outcome = RecommendationOutcome(
            recommendation_id="R2", symbol="TCS", trading_date="2026-08-01",
            actual_entry_price=4000, highest_price_reached=4060,
            lowest_price_reached=3920, closing_price=3950,
            max_gain_pct=1.5, max_drawdown_pct=-2.0,
            target_hit=False, stop_loss_hit=False, final_pnl_pct=-1.25,
        )
        ev = label_recommendation_outcome(rec, outcome)
        assert ev.outcome_label == OutcomeLabel.FALSE_POSITIVE.value


class TestAggregateMetrics:
    def test_empty_evaluations(self):
        metrics = compute_aggregate_metrics([])
        assert metrics.total_trades == 0
        assert metrics.win_rate == 0.0

    def test_mixed_results(self):
        evals = [
            TradeEvaluation(outcome_label="SUCCESSFUL", return_pct=2.5, net_pnl=500),
            TradeEvaluation(outcome_label="FAILED", return_pct=-1.5, net_pnl=-300),
            TradeEvaluation(outcome_label="PARTIALLY_SUCCESSFUL", return_pct=0.5, net_pnl=100),
        ]
        metrics = compute_aggregate_metrics(evals)
        assert metrics.total_trades == 3
        assert metrics.wins == 2
        assert metrics.losses == 1
        assert metrics.win_rate > 60
        assert metrics.total_net_pnl == 300.0
        assert metrics.profit_factor > 1.0
