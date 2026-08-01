import pandas as pd
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def update_mapping():
    url = "https://images.dhan.co/api-data/api-scrip-master.csv"
    logger.info(f"Downloading Dhan scrip master from {url}...")
    
    try:
        df = pd.read_csv(url, low_memory=False)
        # Filter for NSE Equity (SEM_EXM_EXCH_ID == 'NSE' and SEM_SERIES == 'EQ')
        nse_eq = df[(df['SEM_EXM_EXCH_ID'] == 'NSE') & (df['SEM_SERIES'] == 'EQ')]
        
        # Note: Dhan uses SEM_TRADING_SYMBOL for the clean ticker like 'RELIANCE', 'TCS'
        mapping = {}
        for _, row in nse_eq.iterrows():
            symbol = str(row['SEM_TRADING_SYMBOL']).strip()
            sec_id = str(row['SEM_SMST_SECURITY_ID']).strip()
            mapping[symbol] = sec_id
            
        with open('nse_eq_mapping.json', 'w') as f:
            json.dump(mapping, f, indent=4)
            
        logger.info(f"Successfully mapped {len(mapping)} NSE equity symbols.")
    except Exception as e:
        logger.error(f"Failed to update mapping: {e}")

if __name__ == "__main__":
    update_mapping()
