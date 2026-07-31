"""
Automatic failure root-cause analysis for losing trades.

Tags losing trades with identifiable root causes based on
available market data and trade context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from analytics_models import FailureAnalysis, PaperTrade, Recommendation
from clock import trading_date_ist

logger = logging.getLogger(__name__)


# ── Root-cause tag constants ─────────────────────────────────────────
INCORRECT_TREND = "INCORRECT_TREND"
WEAK_ENTRY_TIMING = "WEAK_ENTRY_TIMING"
POOR_SL_PLACEMENT = "POOR_SL_PLACEMENT"
HIGH_VOLATILITY = "HIGH_VOLATILITY"
MARKET_REGIME_MISMATCH = "MARKET_REGIME_MISMATCH"
LOW_CONFIDENCE = "LOW_CONFIDENCE"
STRATEGY_FAILURE = "STRATEGY_FAILURE"
NEWS_EVENT_IMPACT = "NEWS_EVENT_IMPACT"
UNKNOWN = "UNKNOWN"


def analyze_failure(
    trade: PaperTrade,
    rec: Recommendation | None = None,
    market_regime: str = "UNKNOWN",
    vix_value: float = 0.0,
) -> FailureAnalysis:
    """Analyze a losing paper trade and assign root-cause tags.

    Uses heuristic rules based on trade data and market context.
    Multiple tags can apply to a single trade.
    """
    tags: list[str] = []
    notes_parts: list[str] = []

    # Only analyze losing trades
    if trade.net_pnl >= 0:
        return FailureAnalysis(
            trade_id=trade.trade_id,
            recommendation_id=trade.recommendation_id,
            trading_date=trade.trading_date,
            symbol=trade.symbol,
            strategy=trade.strategy,
            root_cause_tags=["NOT_A_LOSS"],
            notes="Trade was profitable — no failure analysis needed.",
        )

    sl_distance = abs(trade.entry_price - trade.planned_sl) if trade.planned_sl > 0 else 0.0

    # 1. Stop-loss hit immediately — poor SL placement or weak entry
    if trade.stop_loss_hit if hasattr(trade, "stop_loss_hit") else (trade.exit_reason == "SL Hit"):
        if sl_distance > 0:
            sl_pct = (sl_distance / trade.entry_price) * 100
            if sl_pct < 0.3:
                tags.append(POOR_SL_PLACEMENT)
                notes_parts.append(f"SL too tight ({sl_pct:.2f}% from entry)")
            else:
                tags.append(WEAK_ENTRY_TIMING)
                notes_parts.append("SL hit — possible late entry after move exhausted")

    # 2. Market regime mismatch
    if rec and rec.action == "BUY" and "BEAR" in market_regime.upper():
        tags.append(MARKET_REGIME_MISMATCH)
        notes_parts.append(f"Long entry in {market_regime} regime")
    elif rec and rec.action == "SELL" and "BULL" in market_regime.upper():
        tags.append(MARKET_REGIME_MISMATCH)
        notes_parts.append(f"Short entry in {market_regime} regime")

    # 3. High volatility
    if vix_value > 20.0:
        tags.append(HIGH_VOLATILITY)
        notes_parts.append(f"India VIX at {vix_value:.1f} — elevated volatility")

    # 4. Low confidence
    if rec and rec.confidence_score > 0 and rec.confidence_score < 40:
        tags.append(LOW_CONFIDENCE)
        notes_parts.append(f"Confidence score {rec.confidence_score:.0f} below threshold")

    # 5. Time exit (strategy couldn't reach TP)
    if trade.exit_reason in ("Time Exit", "EOD Close"):
        if trade.net_pnl < 0:
            tags.append(STRATEGY_FAILURE)
            notes_parts.append(f"Exited on {trade.exit_reason} with loss — target unreachable in session")

    # Fallback
    if not tags:
        tags.append(UNKNOWN)
        notes_parts.append("No specific root cause identified — manual review recommended")

    context = {}
    if rec:
        context["strategy"] = rec.strategy
        context["action"] = rec.action
        context["confidence"] = rec.confidence_score
        context["market_regime"] = rec.market_regime or market_regime
    context["vix"] = vix_value
    context["sl_distance"] = round(sl_distance, 2)
    context["loss_amount"] = round(trade.net_pnl, 2)

    return FailureAnalysis(
        trade_id=trade.trade_id,
        recommendation_id=trade.recommendation_id,
        trading_date=trade.trading_date,
        symbol=trade.symbol,
        strategy=trade.strategy,
        root_cause_tags=tags,
        notes="; ".join(notes_parts),
        context_snapshot=context,
    )
