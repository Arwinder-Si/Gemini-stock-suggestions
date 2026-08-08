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
from pathlib import Path

import pandas as pd

from hermes.config import get_config
from hermes.data.analytics_models import Recommendation
from hermes.data.analytics_mongo import MongoAnalyticsStore
from hermes.domain.earnings_calendar import is_result_day, load_calendar, refresh_buckets
from hermes.clock import trading_date_ist

logger = logging.getLogger(__name__)

PICK_EVENING_LARGE = "evening_large"
PICK_EVENING_SMALL = "evening_small"
PICK_MORNING = "morning"
PIPELINE_STRATEGY = "PIPELINE"

# Heuristic intraday reference levels when no explicit TP/SL from screener
DEFAULT_TARGET_PCT = 0.02
DEFAULT_STOP_PCT = 0.01


def _load_screener_lookup(base_dir: str = ".") -> dict[str, dict]:
    frames = []
    for name in ("screener_results.csv", "screener_results_smallcap.csv"):
        path = os.path.join(base_dir, name)
        if os.path.exists(path):
            frames.append(pd.read_csv(path))
    if not frames:
        return {}
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["Stock"], keep="first")
    return df.set_index("Stock").to_dict(orient="index")


def _load_regime(base_dir: str = ".") -> str:
    path = os.path.join(base_dir, "market_regime.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return "UNKNOWN"


def _load_earnings_calendar(base_dir: str = ".") -> dict | None:
    path = os.path.join(base_dir, "earnings_calendar.json")
    cal = load_calendar(path) if os.path.exists(path) else None
    if cal:
        return refresh_buckets(cal, trading_date_ist())
    return None


def _earnings_indicators(symbol: str, trading_date: str, calendar: dict | None) -> dict:
    if not is_result_day(symbol, trading_date, calendar):
        return {}
    entry = (calendar.get("entries") or {}).get(symbol, {}) if calendar else {}
    return {
        "result_day": True,
        "earnings_result_date": entry.get("result_date"),
        "earnings_source": entry.get("source"),
    }


def _build_recommendation(
    *,
    trading_date: str,
    symbol: str,
    pick_source: str,
    screener_row: dict | None,
    confidence_score: float = 0.0,
    reasoning: str = "",
    extra_indicators: dict | None = None,
    market_regime: str = "UNKNOWN",
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
        market_regime=market_regime,
        supporting_indicators=indicators,
    )


def _persist_evening_plan(
    store: MongoAnalyticsStore,
    plan: dict,
    pick_source: str,
    screener: dict[str, dict],
    *,
    market_regime: str = "UNKNOWN",
    base_dir: str = ".",
) -> int:
    trading_date = plan.get("trading_date", "")
    symbols = plan.get("symbols") or {}
    if not trading_date or not symbols:
        return 0

    count = 0
    calendar = _load_earnings_calendar(base_dir)
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
            market_regime=market_regime,
            extra_indicators=_earnings_indicators(symbol, trading_date, calendar),
        )
        store.save_pipeline_pick(rec)
        count += 1
        logger.info("Saved evening pick %s %s (%s)", trading_date, symbol, pick_source)
    return count


def _persist_morning_plan(
    store: MongoAnalyticsStore,
    plan: dict,
    *,
    market_regime: str = "UNKNOWN",
    base_dir: str = ".",
) -> int:
    trading_date = plan.get("trading_date", "")
    rankings = plan.get("rankings") or []
    if not trading_date or not rankings:
        return 0

    count = 0
    calendar = _load_earnings_calendar(base_dir)
    for row in rankings:
        symbol = row.get("symbol", "")
        if not symbol:
            continue
        extra = {
            "morning_score": row.get("morning_score"),
            "sentiment_7d": row.get("sentiment_7d"),
            "in_evening_plan": row.get("in_evening_plan"),
            "gap_prediction_pct": plan.get("gap_prediction_pct"),
        }
        extra.update(_earnings_indicators(symbol, trading_date, calendar))
        if row.get("earnings_result_today"):
            extra["result_day"] = True
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
            market_regime=market_regime,
            extra_indicators=extra,
        )
        store.save_pipeline_pick(rec)
        count += 1
        logger.info("Saved morning pick %s %s", trading_date, symbol)
    return count


def persist_evening_picks(store: MongoAnalyticsStore, *, base_dir: str = ".") -> int:
    """Save evening screener trade-plan symbols to MongoDB."""
    screener = _load_screener_lookup(base_dir)
    regime = _load_regime(base_dir)
    count = 0
    for plan_file, pick_source in (
        ("trade_plan.json", PICK_EVENING_LARGE),
        ("trade_plan_smallcap.json", PICK_EVENING_SMALL),
    ):
        path = os.path.join(base_dir, plan_file)
        if not os.path.exists(path):
            logger.warning("No %s — skipping %s picks", path, pick_source)
            continue
        with open(path, encoding="utf-8") as f:
            plan = json.load(f)
        count += _persist_evening_plan(store, plan, pick_source, screener, market_regime=regime, base_dir=base_dir)
    return count


def persist_morning_picks(store: MongoAnalyticsStore, *, base_dir: str = ".") -> int:
    """Save morning refined trade-plan symbols to MongoDB."""
    plan_file = os.path.join(base_dir, "morning_trade_plan.json")
    if not os.path.exists(plan_file):
        raise FileNotFoundError(f"{plan_file} not found — run morning pipeline first.")

    with open(plan_file, encoding="utf-8") as f:
        plan = json.load(f)
    regime = _load_regime(base_dir)
    return _persist_morning_plan(store, plan, market_regime=regime, base_dir=base_dir)


def backfill_picks_from_runs(store: MongoAnalyticsStore) -> int:
    """Load trade plans archived under var/runs/<date>/ into MongoDB.

    Used when persist_picks was skipped during cron (e.g. .env not exported)
    but plan files were still copied into run directories.
    """
    from hermes import artifacts

    runs_root = artifacts.runs_dir()
    if not runs_root.is_dir():
        return 0

    total = 0
    for run_path in sorted(runs_root.iterdir()):
        if not run_path.is_dir():
            continue
        base = str(run_path)
        screener = _load_screener_lookup(base)
        regime = _load_regime(base)

        for plan_name, pick_source in (
            ("trade_plan.json", PICK_EVENING_LARGE),
            ("trade_plan_smallcap.json", PICK_EVENING_SMALL),
        ):
            plan_path = run_path / plan_name
            if not plan_path.is_file():
                continue
            with open(plan_path, encoding="utf-8") as f:
                plan = json.load(f)
            total += _persist_evening_plan(
                store, plan, pick_source, screener, market_regime=regime, base_dir=base
            )

        morning_path = run_path / "morning_trade_plan.json"
        if morning_path.is_file():
            with open(morning_path, encoding="utf-8") as f:
                plan = json.load(f)
            total += _persist_morning_plan(store, plan, market_regime=regime, base_dir=base)

    if total:
        logger.info("Backfilled %d pipeline pick(s) from %s", total, runs_root)
    return total


def get_analytics_store() -> MongoAnalyticsStore | None:
    cfg = get_config()
    if not cfg.mongodb_uri:
        return None
    return MongoAnalyticsStore(cfg.mongodb_uri, tls_insecure=cfg.mongodb_tls_insecure)


def recommendation_to_dict(rec: Recommendation) -> dict:
    return asdict(rec)
