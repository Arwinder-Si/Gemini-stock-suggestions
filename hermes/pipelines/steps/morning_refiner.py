"""
Morning trade-plan refiner.

Combines yesterday's post-market screener picks with overnight news sentiment
and global gap prediction to produce an updated morning_trade_plan.json for
today's session.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime

import pandas as pd

from hermes.clock import now_ist, trading_date_ist
from hermes.config import get_config
from hermes.data import market_db
from hermes.domain.morning_score import compute_morning_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_FILE = "morning_trade_plan.json"
MIN_MORNING_SCORE = 60.0


def _load_regime() -> str:
    if os.path.exists("market_regime.txt"):
        with open("market_regime.txt", encoding="utf-8") as f:
            return f.read().strip()
    return "UNKNOWN"


def _load_evening_plan() -> dict[str, str]:
    cfg = get_config()
    plan = cfg.load_trade_plan("trade_plan.json", required=False)
    small = cfg.load_trade_plan("trade_plan_smallcap.json", required=False)
    merged = dict(plan)
    merged.update(small)
    return merged


def _load_screener_rows() -> pd.DataFrame:
    frames = []
    for path in ("screener_results.csv", "screener_results_smallcap.csv"):
        if os.path.exists(path):
            frames.append(pd.read_csv(path))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates(subset=["Stock"], keep="first")


def _load_news() -> pd.DataFrame:
    if os.path.exists("news_features.csv"):
        return pd.read_csv("news_features.csv")
    return pd.DataFrame()


def _load_security_ids() -> dict[str, str]:
    if not os.path.exists("nse_eq_mapping.json"):
        return {}
    with open("nse_eq_mapping.json", encoding="utf-8") as f:
        return json.load(f)


def refine_morning_plan() -> dict:
    """Build and write morning_trade_plan.json. Returns the plan document."""
    cfg = get_config()
    today = trading_date_ist().strftime("%Y-%m-%d")
    evening_symbols = _load_evening_plan()
    screener_df = _load_screener_rows()
    news_df = _load_news()
    mapping = _load_security_ids()
    regime = _load_regime()

    gap = market_db.get_latest_gap_prediction() or {}
    gap_pct = float(gap.get("prediction_pct", 0.0))
    gap_bias = gap.get("bias", "Unknown")

    if screener_df.empty:
        raise FileNotFoundError("No screener_results.csv found. Run the evening pipeline first.")

    news_by_symbol = {}
    if not news_df.empty and "symbol" in news_df.columns:
        news_by_symbol = news_df.set_index("symbol").to_dict(orient="index")

    screener_by_stock = screener_df.set_index("Stock").to_dict(orient="index")

    # Candidates: evening plan symbols + any screener row scoring >= 60
    candidate_symbols: set[str] = set(evening_symbols.keys())
    for stock, row in screener_by_stock.items():
        if float(row.get("Score", 0)) >= 60:
            candidate_symbols.add(stock)

    rankings: list[dict] = []
    for symbol in candidate_symbols:
        scr = screener_by_stock.get(symbol)
        if not scr:
            continue

        news = news_by_symbol.get(symbol, {})
        sentiment = float(news.get("sentiment_7d", 0.0) or 0.0)
        has_reg = bool(news.get("has_neg_reg_news_7d", False))

        morning_score = compute_morning_score(
            screener_score=float(scr["Score"]),
            sentiment_7d=sentiment,
            gap_prediction_pct=gap_pct,
            has_reg_risk=has_reg,
            market_regime=regime,
        )
        if morning_score is None or morning_score < MIN_MORNING_SCORE:
            continue

        sec_id = evening_symbols.get(symbol) or mapping.get(symbol, "")
        if not sec_id:
            logger.warning("No security ID for %s — skipping", symbol)
            continue

        rankings.append({
            "symbol": symbol,
            "morning_score": morning_score,
            "screener_score": int(scr["Score"]),
            "sentiment_7d": round(sentiment, 3),
            "sector": scr.get("Sector", ""),
            "vol_ratio": scr.get("Vol_Ratio", 0),
            "rsi": scr.get("RSI", 0),
            "security_id": str(sec_id),
            "in_evening_plan": symbol in evening_symbols,
        })

    rankings.sort(key=lambda r: r["morning_score"], reverse=True)
    top_n = cfg.screener_top_n
    selected = rankings[:top_n]

    symbols = {r["symbol"]: r["security_id"] for r in selected}

    plan = {
        "trading_date": today,
        "generated_at": now_ist().strftime("%Y-%m-%d %H:%M:%S IST"),
        "source": "morning_refiner",
        "market_regime": regime,
        "gap_prediction_pct": gap_pct,
        "gap_bias": gap_bias,
        "min_morning_score": MIN_MORNING_SCORE,
        "symbols": symbols,
        "rankings": selected,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=4)

    logger.info(
        "Morning plan: %d symbols (from %d candidates, gap %+.2f%%)",
        len(symbols),
        len(candidate_symbols),
        gap_pct,
    )
    for r in selected:
        logger.info(
            "  %s  morning=%.1f  screener=%d  sentiment=%+.3f",
            r["symbol"],
            r["morning_score"],
            r["screener_score"],
            r["sentiment_7d"],
        )

    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Refine evening trade plan for morning session")
    parser.parse_args()
    refine_morning_plan()


if __name__ == "__main__":
    main()
