"""
Post-session Outcome Enricher.
Fetches intraday EOD high/low/close price action to enrich recommendations with actual market outcomes.
"""

from dataclasses import dataclass
import logging
from hermes.data.analytics_models import Recommendation
from hermes.data.analytics_mongo import MongoAnalyticsStore, InMemoryAnalyticsStore

logger = logging.getLogger(__name__)


@dataclass
class RecommendationOutcome:
    recommendation_id: str
    symbol: str
    trading_date: str
    actual_entry_price: float
    highest_price_reached: float
    lowest_price_reached: float
    closing_price: float
    max_gain_pct: float
    max_drawdown_pct: float
    target_hit: bool
    stop_loss_hit: bool
    final_pnl_pct: float


def enrich_recommendation(rec: Recommendation, day_high: float, day_low: float, day_close: float) -> RecommendationOutcome:
    """Enriches a recommendation with post-session price action outcomes."""
    entry = rec.entry_price or day_close

    if rec.action == "BUY":
        max_gain_pct = round(((day_high - entry) / entry) * 100, 2)
        max_drawdown_pct = round(((day_low - entry) / entry) * 100, 2)
        target_hit = (day_high >= rec.target_price) if rec.target_price > 0 else False
        stop_loss_hit = (day_low <= rec.stop_loss) if rec.stop_loss > 0 else False
        final_pnl_pct = round(((day_close - entry) / entry) * 100, 2)
    else:  # SELL
        max_gain_pct = round(((entry - day_low) / entry) * 100, 2)
        max_drawdown_pct = round(((entry - day_high) / entry) * 100, 2)
        target_hit = (day_low <= rec.target_price) if rec.target_price > 0 else False
        stop_loss_hit = (day_high >= rec.stop_loss) if rec.stop_loss > 0 else False
        final_pnl_pct = round(((entry - day_close) / entry) * 100, 2)

    return RecommendationOutcome(
        recommendation_id=rec.recommendation_id,
        symbol=rec.symbol,
        trading_date=rec.trading_date,
        actual_entry_price=entry,
        highest_price_reached=day_high,
        lowest_price_reached=day_low,
        closing_price=day_close,
        max_gain_pct=max_gain_pct,
        max_drawdown_pct=max_drawdown_pct,
        target_hit=target_hit,
        stop_loss_hit=stop_loss_hit,
        final_pnl_pct=final_pnl_pct,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger.info("Outcome enricher completed (library module; batch enrichment runs via analytics pipeline).")
