"""
Intraday trade plan generator — filters top screener stocks, maps to Security IDs,
and writes structured trade_plan.json with provenance and date validation metadata.
"""

import argparse
import pandas as pd
import json
import logging
import os
from datetime import datetime, timedelta
from hermes.config import get_config
from hermes.clock import now_ist, trading_date_ist

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def generate_trade_plan(universe: str = "large") -> None:
    """
    Reads screener_results.csv, filters top stocks (Score >= 70),
    maps to Dhan Security IDs, and writes structured trade_plan.json.
    """
    in_file = "screener_results_smallcap.csv" if universe == "small" else "screener_results.csv"
    out_file = "trade_plan_smallcap.json" if universe == "small" else "trade_plan.json"

    cfg = get_config()
    top_n = min(3, cfg.screener_top_n) if universe == "small" else cfg.screener_top_n

    if not os.path.exists(in_file):
        raise FileNotFoundError(f"Screener file {in_file} not found! Run comprehensive_screener.py first.")

    if not os.path.exists('nse_eq_mapping.json'):
        raise FileNotFoundError("nse_eq_mapping.json not found! Run update_security_ids.py first.")

    with open('nse_eq_mapping.json', 'r') as f:
        mapping = json.load(f)

    df = pd.read_csv(in_file)
    
    # Filter for high quality setups (Score >= 70) and take top N
    filtered_df = df[df['Score'] >= 70] if not df.empty and 'Score' in df.columns else pd.DataFrame()
    top_stocks = filtered_df.head(top_n)

    # Next trading session date
    now = now_ist()
    target_date = now.date()
    # If generating after market hours (e.g. 3:45 PM), target is next day
    if now.time() >= datetime.strptime("15:30", "%H:%M").time():
        target_date = target_date + timedelta(days=1)

    symbols_map = {}
    if not top_stocks.empty:
        for _, row in top_stocks.iterrows():
            symbol = row['Stock']
            if symbol in mapping:
                symbols_map[symbol] = str(mapping[symbol])
                logger.info(f"Added {symbol} (Score: {row['Score']}) to {universe} trade plan.")
            else:
                logger.warning(f"Could not find Security ID for {symbol}.")
    else:
        logger.warning(f"No breakout setups (Score >= 70) found in {universe} universe.")

    structured_plan = {
        "trading_date": target_date.strftime("%Y-%m-%d"),
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S IST"),
        "universe": universe,
        "symbols": symbols_map,
    }

    with open(out_file, 'w') as f:
        json.dump(structured_plan, f, indent=4)

    logger.info(f"{universe.title()} trade plan generated for {target_date} with {len(symbols_map)} stocks.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", choices=["large", "small"], default="large")
    args, _ = parser.parse_known_args()
    generate_trade_plan(args.universe)
