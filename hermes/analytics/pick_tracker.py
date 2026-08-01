"""
Persist evening and morning pipeline stock picks to MongoDB for outcome tracking.

These picks are separate from live ORB paper trades — they represent what the
screener recommended, whether or not the agent executed them.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict

import pandas as pd

from hermes.config import get_config
from hermes.data.analytics_models import Recommendation
from hermes.data.analytics_mongo import MongoAnalyticsStore

logger = logging.getLogger(__name__)

PICK_EVENING_LARGE = "evening_large"
PICK_EVENING_SMALL = "evening_small"
PICK_MORNING = "morning"
PIPELINE_STRATEGY = "PIPELINE"

# Heuristic intraday reference levels when no explicit TP/SL from screener
DEFAULT_TARGET_PCT = 0.02
DEFAULT_STOP_PCT = 0.01


def _load_screener_lookup() -> dict[str, dict]:
    frames = []
    for path in ("screener_results.csv", "screener_results_smallcap.csv"):
        if os.path.exists(path):
            frames.append(pd.read_csv(path))
    if not frames:
        return {}
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["Stock"], keep="first")
    return df.set_index("Stock").to_dict(orient="index")


def _load_regime() -> str:
    if os.path.exists("market_regime.txt"):
        with open("market_regime.txt", encoding="utf-8") as f:
            return f.read().strip()
    return "UNKNOWN"


def _build_recommendation(
    *,
    trading_date: str,
    symbol: str,
    pick_source: str,
    screener_row: dict | None,
    confidence_score: float = 0.0,
    reasoning: str = "",
    extra_indicators: dict | None = None,
) -> Recommendation:
    close = float(screener_row.get("Close", 0)) if screener_row else 0.0
    sector = str(screener_row.get("Sector", "")) if screener_row else ""
    entry = close if close > 0 else 0.0
    target = round(entry * (1 + DEFAULT_TARGET_PCT), 2) if entry > 0 else 0.0
    stop = round(entry * (1 - DEFAULT_STOP_PCT), 2) if entry > 0 else 0.0

    indicators = dict(extra_indicators or {})
    if screener_row:
        indicators.update({
            "screener_score": screener_row.get("Score"),
            "vol_ratio": screener_row.get("Vol_Ratio"),
            "rsi": screener_row.get("RSI"),
        })

    return Recommendation(
        trading_date=trading_date,
        symbol=symbol,
        sector=sector,
        strategy=PIPELINE_STRATEGY,
        pick_source=pick_source,
        action="BUY",
        entry_price=entry,
        stop_loss=stop,
        target_price=target,
        confidence_score=confidence_score,
        reasoning=reasoning,
        market_regime=_load_regime(),
        supporting_indicators=indicators,
    )


def persist_evening_picks(store: MongoAnalyticsStore) -> int:
    """Save evening screener trade-plan symbols to MongoDB."""
    count = 0
    screener = _load_screener_lookup()
    plans = [
        ("trade_plan.json", PICK_EVENING_LARGE),
        ("trade_plan_smallcap.json", PICK_EVENING_SMALL),
    ]

    for plan_file, pick_source in plans:
        if not os.path.exists(plan_file):
            logger.warning("No %s — skipping %s picks", plan_file, pick_source)
            continue

        with open(plan_file, encoding="utf-8") as f:
            plan = json.load(f)

        trading_date = plan.get("trading_date", "")
        symbols = plan.get("symbols") or {}
        if not trading_date or not symbols:
            logger.warning("%s has no trading_date or symbols", plan_file)
            continue

        for symbol in symbols:
            row = screener.get(symbol)
            score = float(row.get("Score", 0)) if row else 0.0
            rec = _build_recommendation(
                trading_date=trading_date,
                symbol=symbol,
                pick_source=pick_source,
                screener_row=row,
                confidence_score=score,
                reasoning=f"Evening screener pick ({pick_source})",
            )
            store.save_pipeline_pick(rec)
            count += 1
            logger.info("Saved evening pick %s %s (%s)", trading_date, symbol, pick_source)

    return count


def persist_morning_picks(store: MongoAnalyticsStore) -> int:
    """Save morning refined trade-plan symbols to MongoDB."""
    plan_file = "morning_trade_plan.json"
    if not os.path.exists(plan_file):
        raise FileNotFoundError(f"{plan_file} not found — run morning pipeline first.")

    with open(plan_file, encoding="utf-8") as f:
        plan = json.load(f)

    trading_date = plan.get("trading_date", "")
    rankings = plan.get("rankings") or []
    if not trading_date:
        raise ValueError(f"{plan_file} missing trading_date")

    count = 0
    for row in rankings:
        symbol = row.get("symbol", "")
        if not symbol:
            continue
        rec = _build_recommendation(
            trading_date=trading_date,
            symbol=symbol,
            pick_source=PICK_MORNING,
            screener_row={
                "Close": 0,
                "Sector": row.get("sector", ""),
                "Score": row.get("screener_score", 0),
                "Vol_Ratio": row.get("vol_ratio", 0),
                "RSI": row.get("rsi", 0),
            },
            confidence_score=float(row.get("morning_score", 0)),
            reasoning="Morning refiner pick",
            extra_indicators={
                "morning_score": row.get("morning_score"),
                "sentiment_7d": row.get("sentiment_7d"),
                "in_evening_plan": row.get("in_evening_plan"),
                "gap_prediction_pct": plan.get("gap_prediction_pct"),
            },
        )
        store.save_pipeline_pick(rec)
        count += 1
        logger.info("Saved morning pick %s %s", trading_date, symbol)

    return count


def get_analytics_store() -> MongoAnalyticsStore | None:
    cfg = get_config()
    if not cfg.mongodb_uri:
        return None
    return MongoAnalyticsStore(cfg.mongodb_uri, tls_insecure=cfg.mongodb_tls_insecure)


def recommendation_to_dict(rec: Recommendation) -> dict:
    return asdict(rec)
