"""
Post-session Outcome Enricher.

Fetches intraday EOD high/low/close price action to enrich pipeline stock picks
(evening screener + morning refiner) with actual market outcomes.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta

from hermes.analytics.evaluation import label_recommendation_outcome
from hermes.analytics.pick_tracker import PIPELINE_STRATEGY, get_analytics_store
from hermes.clock import now_ist, trading_date_ist
from hermes.data.analytics_models import Recommendation, RecommendationOutcome

logger = logging.getLogger(__name__)

# Intraday reference levels for pipeline picks (open → close performance)
PIPELINE_TARGET_PCT = 0.02
PIPELINE_STOP_PCT = 0.01


def _resolve_entry_and_levels(
    rec: Recommendation, day_open: float
) -> tuple[float, float, float]:
    """Pipeline picks benchmark from session open; ORB picks use stored levels."""
    if rec.pick_source or rec.strategy == PIPELINE_STRATEGY:
        entry = day_open
        target = round(day_open * (1 + PIPELINE_TARGET_PCT), 2)
        stop = round(day_open * (1 - PIPELINE_STOP_PCT), 2)
        return entry, target, stop
    entry = rec.entry_price if rec.entry_price > 0 else day_open
    return entry, rec.target_price, rec.stop_loss


def enrich_recommendation(
    rec: Recommendation, day_open: float, day_high: float, day_low: float, day_close: float
) -> RecommendationOutcome:
    """Enrich a recommendation with post-session price action outcomes."""
    entry, target_price, stop_loss = _resolve_entry_and_levels(rec, day_open)

    if rec.action == "BUY":
        max_gain_pct = round(((day_high - entry) / entry) * 100, 2) if entry > 0 else 0.0
        max_drawdown_pct = round(((day_low - entry) / entry) * 100, 2) if entry > 0 else 0.0
        target_hit = (day_high >= target_price) if target_price > 0 else False
        stop_loss_hit = (day_low <= stop_loss) if stop_loss > 0 else False
        final_pnl_pct = round(((day_close - entry) / entry) * 100, 2) if entry > 0 else 0.0
    else:
        max_gain_pct = round(((entry - day_low) / entry) * 100, 2) if entry > 0 else 0.0
        max_drawdown_pct = round(((entry - day_high) / entry) * 100, 2) if entry > 0 else 0.0
        target_hit = (day_low <= target_price) if target_price > 0 else False
        stop_loss_hit = (day_high >= stop_loss) if stop_loss > 0 else False
        final_pnl_pct = round(((entry - day_close) / entry) * 100, 2) if entry > 0 else 0.0

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


def fetch_day_ohlc(symbol: str, trading_date: str) -> dict[str, float] | None:
    """Fetch open/high/low/close for an NSE symbol on a specific date via yfinance."""
    import pandas as pd
    import yfinance as yf

    dt = datetime.strptime(trading_date, "%Y-%m-%d").date()
    start = dt.strftime("%Y-%m-%d")
    end = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
    ticker = f"{symbol}.NS"

    try:
        df = yf.download(
            ticker, start=start, end=end, progress=False, auto_adjust=True, threads=False
        )
    except Exception as exc:
        logger.warning("yfinance error for %s on %s: %s", symbol, trading_date, exc)
        return None

    if df is None or df.empty:
        logger.warning("No OHLC data for %s on %s", symbol, trading_date)
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    row = df.iloc[0]
    return {
        "open": float(row["Open"]),
        "high": float(row["High"]),
        "low": float(row["Low"]),
        "close": float(row["Close"]),
    }


def enrich_pick(store, rec: Recommendation) -> bool:
    """Fetch market data and save evaluation for one pipeline pick."""
    ohlc = fetch_day_ohlc(rec.symbol, rec.trading_date)
    if not ohlc:
        return False

    outcome = enrich_recommendation(
        rec,
        day_open=ohlc["open"],
        day_high=ohlc["high"],
        day_low=ohlc["low"],
        day_close=ohlc["close"],
    )
    evaluation = label_recommendation_outcome(rec, outcome)
    store.save_evaluation({
        **asdict(evaluation),
        "pick_source": rec.pick_source,
        "outcome": asdict(outcome),
        "evaluated_at": now_ist().strftime("%Y-%m-%d %H:%M:%S IST"),
    })
    logger.info(
        "Enriched %s %s (%s): return=%+.2f%% label=%s",
        rec.trading_date,
        rec.symbol,
        rec.pick_source,
        outcome.final_pnl_pct,
        evaluation.outcome_label,
    )
    return True


def enrich_due_picks(store, through_date: date | None = None, *, force: bool = False) -> int:
    """
    Enrich pipeline picks whose trading session has ended and lack an evaluation.

    Default: enrich picks with trading_date <= today (IST).
    """
    through = through_date or trading_date_ist()
    through_str = through.strftime("%Y-%m-%d")
    evaluated_ids = store.get_evaluated_recommendation_ids()
    picks = store.get_pipeline_picks(end_date=through_str)

    count = 0
    skipped_future = 0
    for rec in picks:
        if rec.trading_date > through_str:
            skipped_future += 1
            continue
        if rec.recommendation_id in evaluated_ids and not force:
            continue
        if enrich_pick(store, rec):
            count += 1
            evaluated_ids.add(rec.recommendation_id)
    if skipped_future:
        logger.info(
            "Skipped %d pick(s) with trading_date after %s (session not yet traded)",
            skipped_future,
            through_str,
        )
    return count


def enrich_for_date(store, trading_date: str, *, force: bool = False) -> int:
    """Enrich all pipeline picks for a specific trading date."""
    evaluated_ids = store.get_evaluated_recommendation_ids()
    picks = store.get_pipeline_picks(start_date=trading_date, end_date=trading_date)
    count = 0
    for rec in picks:
        if rec.recommendation_id in evaluated_ids and not force:
            continue
        if enrich_pick(store, rec):
            count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Enrich pipeline picks with session outcomes")
    parser.add_argument(
        "--date",
        default=None,
        help="Trading date to enrich (YYYY-MM-DD). Default: enrich all due picks.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-enrich picks that already have evaluations",
    )
    args = parser.parse_args(argv)

    store = get_analytics_store()
    if store is None:
        logger.error("MONGODB_URI not configured — cannot enrich outcomes")
        return 1

    if args.date:
        count = enrich_for_date(store, args.date, force=args.force)
    else:
        count = enrich_due_picks(store, force=args.force)

    logger.info("Outcome enricher completed — enriched %d pick(s)", count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
