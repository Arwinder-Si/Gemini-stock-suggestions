import yfinance as yf
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

# List of top Nifty 50 stocks for scanning
tickers = [
    'RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'ICICIBANK.NS', 
    'HINDUNILVR.NS', 'SBIN.NS', 'BAJFINANCE.NS', 'BHARTIARTL.NS', 'ITC.NS', 
    'KOTAKBANK.NS', 'LT.NS', 'ASIANPAINT.NS', 'AXISBANK.NS', 'MARUTI.NS', 
    'SUNPHARMA.NS', 'TITAN.NS', 'ULTRACEMCO.NS', 'WIPRO.NS', 'TATASTEEL.NS',
    'M&M.NS', 'POWERGRID.NS', 'NTPC.NS', 'HCLTECH.NS', 'BAJAJFINSV.NS',
    'TATAMOTORS.NS', 'JSWSTEEL.NS', 'ADANIENT.NS', 'ONGC.NS', 'COALINDIA.NS'
]

print("Scanning for breakouts in Nifty Top 30...")
breakouts = []

# Fetch data in bulk for speed
data = yf.download(tickers, period="1y", interval="1d", progress=False)

for ticker in tickers:
    try:
        df = data['Close'][ticker].dropna()
        if len(df) < 50:
            continue
            
        current_close = df.iloc[-1]
        
        # Condition 1: 52-week High Breakout
        high_52w = df.max()
        # If current close is within 2% of 52 week high, or broke it today
        if current_close >= high_52w * 0.98:
            breakouts.append({
                'Stock': ticker.replace('.NS', ''),
                'Close': round(current_close, 2),
                'Type': 'Near/At 52-Week High Breakout'
            })
            continue # move to next so we don't double count
            
        # Condition 2: Bollinger Band Breakout (20, 2)
        sma_20 = df.rolling(window=20).mean()
        std_20 = df.rolling(window=20).std()
        upper_band = sma_20 + (std_20 * 2)
        
        # Condition: closed above upper band today, but yesterday was below
        if current_close > upper_band.iloc[-1] and df.iloc[-2] <= upper_band.iloc[-2]:
            breakouts.append({
                'Stock': ticker.replace('.NS', ''),
                'Close': round(current_close, 2),
                'Type': 'Bollinger Band Breakout'
            })
            
    except Exception as e:
        pass

if not breakouts:
    print("No immediate breakout setups found in the scanned universe today.")
else:
    results_df = pd.DataFrame(breakouts)
    print("\n--- Potential Breakout Candidates ---")
    print(results_df.to_string(index=False))
