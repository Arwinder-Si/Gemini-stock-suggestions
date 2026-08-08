"""
Build earnings_calendar.json for the Hermes universe.

Runs after news_sentiment in the evening pipeline (and optionally before morning
refiner to refresh date buckets). No API keys required — uses yfinance calendar
and headline parsing from news_features.csv.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import pandas as pd

from hermes.clock import now_ist, trading_date_ist
from hermes.domain.earnings_calendar import (
    CALENDAR_FILE,
    build_calendar_document,
    load_calendar,
    refresh_buckets,
    save_calendar,
)
from hermes.pipelines.steps.news_sentiment import ALL_TICKERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _collect_symbols() -> list[str]:
    symbols = list(ALL_TICKERS)
    for path in ("screener_results.csv", "screener_results_smallcap.csv"):
        if os.path.exists(path):
            df = pd.read_csv(path)
            if "Stock" in df.columns:
                symbols.extend(df["Stock"].astype(str).tolist())
    for plan in ("trade_plan.json", "trade_plan_smallcap.json", "morning_trade_plan.json"):
        if os.path.exists(plan):
            import json

            with open(plan, encoding="utf-8") as f:
                data = json.load(f)
            symbols.extend((data.get("symbols") or {}).keys())
            for row in data.get("rankings") or []:
                if row.get("symbol"):
                    symbols.append(row["symbol"])
    # preserve order, dedupe
    return list(dict.fromkeys(s for s in symbols if s))


def _load_news_rows() -> list[dict]:
    if not os.path.exists("news_features.csv"):
        return []
    df = pd.read_csv("news_features.csv")
    return df.to_dict(orient="records")


def run(*, refresh_only: bool = False, max_symbols: int | None = None) -> dict:
    ref = trading_date_ist()
    if refresh_only:
        existing = load_calendar()
        if not existing:
            logger.warning("No %s — running full build instead of refresh", CALENDAR_FILE)
            refresh_only = False
        else:
            doc = refresh_buckets(existing, ref)
            doc["generated_at"] = now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
            save_calendar(doc)
            logger.info(
                "Refreshed earnings buckets: %d today, %d tomorrow",
                len(doc.get("result_today", [])),
                len(doc.get("result_tomorrow", [])),
            )
            return doc

    symbols = _collect_symbols()
    if max_symbols:
        symbols = symbols[:max_symbols]

    logger.info("Building earnings calendar for %d symbols (as_of=%s)", len(symbols), ref)
    doc = build_calendar_document(
        symbols,
        ref,
        news_rows=_load_news_rows(),
        generated_at=now_ist().strftime("%Y-%m-%d %H:%M:%S IST"),
    )
    save_calendar(doc)
    logger.info(
        "Earnings calendar saved: %d entries, %d result tomorrow, %d result today",
        len(doc.get("entries", {})),
        len(doc.get("result_tomorrow", [])),
        len(doc.get("result_today", [])),
    )
    if doc.get("result_tomorrow"):
        logger.info("  Tomorrow: %s", ", ".join(doc["result_tomorrow"][:15]))
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build NSE earnings/results calendar")
    parser.add_argument(
        "--refresh-only",
        action="store_true",
        help="Recompute today/tomorrow buckets from existing entries (no yfinance calls)",
    )
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=None,
        help="Limit yfinance lookups (for testing)",
    )
    args = parser.parse_args(argv)
    run(refresh_only=args.refresh_only, max_symbols=args.max_symbols)
    return 0


if __name__ == "__main__":
    sys.exit(main())
