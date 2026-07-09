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
    cfg = get_config()
    top_n = cfg.screener_top_n
    
    if not os.path.exists('screener_results.csv'):
        logger.error("screener_results.csv not found! Run comprehensive_screener.py first.")
        return
        
    if not os.path.exists('nse_eq_mapping.json'):
        logger.error("nse_eq_mapping.json not found! Run update_security_ids.py first.")
        return

    # Load mapping
    with open('nse_eq_mapping.json', 'r') as f:
        mapping = json.load(f)

    # Load screener results
    df = pd.read_csv('screener_results.csv')
    
    # Filter for high quality setups (e.g. Score >= 70) and take top N
    df = df[df['Score'] >= 70]
    top_stocks = df.head(top_n)
    
    if top_stocks.empty:
        logger.warning("No high-quality breakout setups found today. No trades planned.")
        trade_plan = {}
    else:
        trade_plan = {}
        for _, row in top_stocks.iterrows():
            symbol = row['Stock']
            if symbol in mapping:
                trade_plan[symbol] = mapping[symbol]
                logger.info(f"Added {symbol} (Score: {row['Score']}) to intraday trade plan.")
            else:
                logger.warning(f"Could not find Security ID for {symbol}.")
                
    with open('trade_plan.json', 'w') as f:
        json.dump(trade_plan, f, indent=4)
        
    logger.info(f"Trade plan generated with {len(trade_plan)} stocks.")

if __name__ == "__main__":
    generate_trade_plan()
