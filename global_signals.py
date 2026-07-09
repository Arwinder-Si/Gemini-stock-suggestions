"""
global_signals.py
-----------------
Fetches overnight global data (US markets, Asian markets, commodities, yields)
Calculates a weighted Gap Prediction for the Indian market open.
Saves results to SQLite using market_db.py.
"""

import yfinance as yf
import pandas as pd
import market_db

# The global signals to track
SYMBOLS = {
    "S&P 500": "^GSPC",
    "Nasdaq": "^IXIC",
    "Nikkei": "^N225",
    "Hang Seng": "^HSI",
    "Crude Oil": "BZ=F",  # Brent
    "Gold": "GC=F",
    "US 10Y Yield": "^TNX",
    "Dollar Index": "DX-Y.NYB",
    "Gift Nifty Proxy": "^NSEI" # yfinance lacks real-time Gift Nifty; we use previous Nifty close as a base if needed, but it's better to calculate gap entirely off global beta.
}

# Weights for gap prediction.
# For example, positive S&P means positive gap (weight = 0.35)
# Positive Crude Oil means negative gap for India (weight = -0.15)
WEIGHTS = {
    "S&P 500": 0.35,
    "Nikkei": 0.15,
    "Hang Seng": 0.15,
    "Crude Oil": -0.15,
    "Dollar Index": -0.10,
    "US 10Y Yield": -0.10,
    "Gold": 0.0,
    "Nasdaq": 0.0  # Already highly correlated with S&P, tracked for info only
}


def fetch_global_data() -> pd.DataFrame:
    """Fetch 2 days of data to compute 1-day change %."""
    results = []
    
    for name, ticker in SYMBOLS.items():
        try:
            # We fetch 5 days to ensure we get at least 2 valid trading days 
            # (handling weekends/holidays)
            df = yf.download(ticker, period="5d", interval="1d", progress=False)
            
            if df.empty or len(df) < 2:
                continue
                
            # yfinance returns multi-index columns sometimes
            if isinstance(df.columns, pd.MultiIndex):
                close_series = df['Close'].iloc[:, 0].dropna()
            else:
                close_series = df['Close'].dropna()
                
            if len(close_series) < 2:
                continue
                
            current_close = float(close_series.iloc[-1])
            prev_close = float(close_series.iloc[-2])
            
            change_pct = ((current_close / prev_close) - 1.0) * 100.0
            
            results.append({
                "signal_name": name,
                "value": current_close,
                "change_pct": change_pct
            })
            
        except Exception as e:
            print(f"Failed to fetch {name}: {e}")
            
    return pd.DataFrame(results).set_index("signal_name")


def calculate_gap_prediction(df: pd.DataFrame):
    """
    Compute weighted prediction for Indian market open.
    Example: if prediction = +0.5%, we expect a 0.5% gap up.
    """
    total_prediction = 0.0
    
    for name, weight in WEIGHTS.items():
        if name in df.index:
            change_pct = df.loc[name, 'change_pct']
            total_prediction += (change_pct * weight)
            
    # Add a slight multiplier since Nifty beta to S&P is often > 1.0
    total_prediction *= 1.2 
    
    # Determine bias label
    if total_prediction >= 0.5:
        bias = "Strong Bullish Open (Gap Up > 0.5%)"
    elif total_prediction > 0.1:
        bias = "Mild Bullish Open"
    elif total_prediction > -0.1:
        bias = "Flat / Neutral Open"
    elif total_prediction > -0.5:
        bias = "Mild Bearish Open"
    else:
        bias = "Strong Bearish Open (Gap Down < -0.5%)"
        
    return total_prediction, bias


def main():
    print("Fetching global market data...")
    df = fetch_global_data()
    
    if df.empty:
        print("Failed to fetch any global data.")
        return
        
    print(df[['value', 'change_pct']].round(3))
    
    print("\nSaving to database...")
    market_db.save_global_signals(df)
    
    pred_pct, bias = calculate_gap_prediction(df)
    print(f"\nGap Prediction: {pred_pct:+.2f}%")
    print(f"Bias: {bias}")
    
    market_db.save_gap_prediction(pred_pct, bias)
    print("Done.")

if __name__ == "__main__":
    main()
