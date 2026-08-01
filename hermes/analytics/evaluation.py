"""
Rule-based trade evaluation and recommendation labeling.

Labels each completed trade or recommendation outcome as:
- SUCCESSFUL, PARTIALLY_SUCCESSFUL, FAILED
- MISSED_OPPORTUNITY, FALSE_POSITIVE

Computes aggregate metrics: accuracy, win rate, avg return/loss, profit factor.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from hermes.data.analytics_models import PaperTrade, Recommendation
from hermes.pipelines.steps.outcome_enricher import RecommendationOutcome

logger = logging.getLogger(__name__)


class OutcomeLabel(str, Enum):
    SUCCESSFUL = "SUCCESSFUL"
    PARTIALLY_SUCCESSFUL = "PARTIALLY_SUCCESSFUL"
    FAILED = "FAILED"
    MISSED_OPPORTUNITY = "MISSED_OPPORTUNITY"
    FALSE_POSITIVE = "FALSE_POSITIVE"


@dataclass
class TradeEvaluation:
    """Evaluation record for a single trade or recommendation."""
    recommendation_id: str = ""
    trade_id: str = ""
    trading_date: str = ""
    symbol: str = ""
    outcome_label: str = ""
    net_pnl: float = 0.0
    return_pct: float = 0.0
    target_hit: bool = False
    stop_loss_hit: bool = False
    notes: str = ""


def label_paper_trade(trade: PaperTrade) -> TradeEvaluation:
    """Assign an outcome label to a completed paper trade based on P&L and exit reason."""
    if trade.target_hit or (trade.net_pnl > 0 and trade.exit_reason == "TP Hit"):
        label = OutcomeLabel.SUCCESSFUL
    elif trade.net_pnl > 0:
        label = OutcomeLabel.PARTIALLY_SUCCESSFUL
    elif trade.stop_loss_hit or trade.net_pnl <= 0:
        label = OutcomeLabel.FAILED
    else:
        label = OutcomeLabel.FAILED

    return TradeEvaluation(
        recommendation_id=trade.recommendation_id,
        trade_id=trade.trade_id,
        trading_date=trade.trading_date,
        symbol=trade.symbol,
        outcome_label=label.value,
        net_pnl=trade.net_pnl,
        return_pct=trade.return_pct,
        target_hit=trade.target_hit if hasattr(trade, "target_hit") else False,
        stop_loss_hit=trade.stop_loss_hit if hasattr(trade, "stop_loss_hit") else False,
    )


def label_recommendation_outcome(
    rec: Recommendation, outcome: RecommendationOutcome
) -> TradeEvaluation:
    """Label a recommendation that may or may not have been traded."""
    if outcome.target_hit:
        label = OutcomeLabel.SUCCESSFUL
    elif outcome.stop_loss_hit:
        label = OutcomeLabel.FAILED
    elif outcome.final_pnl_pct > 0:
        label = OutcomeLabel.PARTIALLY_SUCCESSFUL
    elif outcome.max_gain_pct > 1.0 and outcome.final_pnl_pct <= 0:
        label = OutcomeLabel.FALSE_POSITIVE
    else:
        label = OutcomeLabel.FAILED

    return TradeEvaluation(
        recommendation_id=outcome.recommendation_id,
        trading_date=outcome.trading_date,
        symbol=outcome.symbol,
        outcome_label=label.value,
        net_pnl=0.0,  # No actual trade
        return_pct=outcome.final_pnl_pct,
        target_hit=outcome.target_hit,
        stop_loss_hit=outcome.stop_loss_hit,
        notes=f"Max gain: {outcome.max_gain_pct:.2f}%, Max DD: {outcome.max_drawdown_pct:.2f}%",
    )


@dataclass
class AggregateMetrics:
    """Summary performance metrics across a set of evaluations."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_return_pct: float = 0.0
    avg_loss_pct: float = 0.0
    total_net_pnl: float = 0.0
    profit_factor: float = 0.0
    accuracy: float = 0.0  # (SUCCESSFUL + PARTIALLY_SUCCESSFUL) / total


def compute_aggregate_metrics(evaluations: list[TradeEvaluation]) -> AggregateMetrics:
    """Compute aggregate performance metrics from a list of evaluations."""
    if not evaluations:
        return AggregateMetrics()

    total = len(evaluations)
    wins = sum(1 for e in evaluations if e.outcome_label in (
        OutcomeLabel.SUCCESSFUL.value, OutcomeLabel.PARTIALLY_SUCCESSFUL.value
    ))
    losses = total - wins

    positive_returns = [e.return_pct for e in evaluations if e.return_pct > 0]
    negative_returns = [e.return_pct for e in evaluations if e.return_pct <= 0]

    avg_return = sum(positive_returns) / len(positive_returns) if positive_returns else 0.0
    avg_loss = sum(negative_returns) / len(negative_returns) if negative_returns else 0.0

    total_gains = sum(positive_returns)
    total_losses = abs(sum(negative_returns))
    profit_factor = total_gains / total_losses if total_losses > 0 else float("inf") if total_gains > 0 else 0.0

    return AggregateMetrics(
        total_trades=total,
        wins=wins,
        losses=losses,
        win_rate=(wins / total) * 100 if total > 0 else 0.0,
        avg_return_pct=round(avg_return, 2),
        avg_loss_pct=round(avg_loss, 2),
        total_net_pnl=round(sum(e.net_pnl for e in evaluations), 2),
        profit_factor=round(profit_factor, 2),
        accuracy=round((wins / total) * 100, 2) if total > 0 else 0.0,
    )
