import argparse
import pandas as pd
import json
import logging
import os
from config import get_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def generate_trade_plan():
    """
    Reads screener_results.csv, filters the top N stocks, 
    maps them to Dhan Security IDs, and writes trade_plan.json.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", choices=["large", "small"], default="large")
    args, unknown = parser.parse_known_args()
    
    in_file = "screener_results_smallcap.csv" if args.universe == "small" else "screener_results.csv"
    out_file = "trade_plan_smallcap.json" if args.universe == "small" else "trade_plan.json"
    
    cfg = get_config()
    top_n = cfg.screener_top_n
    
    if not os.path.exists(in_file):
        logger.error(f"{in_file} not found! Run comprehensive_screener.py first.")
        return
        
    if not os.path.exists('nse_eq_mapping.json'):
        logger.error("nse_eq_mapping.json not found! Run update_security_ids.py first.")
        return

    # Load mapping
    with open('nse_eq_mapping.json', 'r') as f:
        mapping = json.load(f)

    # Load screener results
    df = pd.read_csv(in_file)
    
    # Filter for high quality setups (e.g. Score >= 70) and take top N
    df = df[df['Score'] >= 70]
    top_stocks = df.head(top_n)
    
    if top_stocks.empty:
        logger.warning(f"No high-quality breakout setups found today in {args.universe} universe. No trades planned.")
        trade_plan = {}
    else:
        trade_plan = {}
        for _, row in top_stocks.iterrows():
            symbol = row['Stock']
            if symbol in mapping:
                trade_plan[symbol] = mapping[symbol]
                logger.info(f"Added {symbol} (Score: {row['Score']}) to {args.universe} trade plan.")
            else:
                logger.warning(f"Could not find Security ID for {symbol}.")
                
    with open(out_file, 'w') as f:
        json.dump(trade_plan, f, indent=4)
        
    logger.info(f"{args.universe.title()} trade plan generated with {len(trade_plan)} stocks.")

if __name__ == "__main__":
    generate_trade_plan()
