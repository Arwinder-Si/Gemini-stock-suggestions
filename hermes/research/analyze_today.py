import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

stocks = ['AFFLE.NS', 'BIOCON.NS', 'ABBOTINDIA.NS', 'GLENMARK.NS', 'SUNPHARMA.NS']

for stock in stocks:
    print(f"\n--- {stock} ---")
    try:
        # Fetch 5-minute data for the last 1 day
        df = yf.download(stock, period='1d', interval='5m', progress=False)
        if df.empty:
            print("No data available.")
            continue
            
        if isinstance(df.columns, pd.MultiIndex):
            # Flatten multi-index
            df.columns = df.columns.droplevel(1)
            
        # Ensure timezone-naive for simplicity if needed
        # df.index = df.index.tz_convert('Asia/Kolkata')
        
        # Get the first 15 mins (9:15 to 9:30)
        # Assuming the first 3 candles (9:15, 9:20, 9:25) represent the 15-min ORB
        orb_df = df.iloc[:3]
        if len(orb_df) < 3:
            print("Not enough candles for ORB.")
            continue
            
        orb_high = float(orb_df['High'].max())
        orb_low = float(orb_df['Low'].min())
        
        print(f"ORB High: {orb_high:.2f}")
        print(f"ORB Low:  {orb_low:.2f}")
        
        # Check rest of the day
        rest_of_day = df.iloc[3:]
        
        # Find if it broke high or low first
        broke_high_time = None
        broke_low_time = None
        
        for idx, row in rest_of_day.iterrows():
            if broke_high_time is None and float(row['High']) > orb_high:
                broke_high_time = idx
            if broke_low_time is None and float(row['Low']) < orb_low:
                broke_low_time = idx
                
        if broke_high_time and (not broke_low_time or broke_high_time < broke_low_time):
            print(f"Triggered LONG at {broke_high_time.strftime('%H:%M')}")
            # check max favorable excursion
            after_trigger = rest_of_day.loc[broke_high_time:]
            max_high = float(after_trigger['High'].max())
            print(f"Max profit potential: {((max_high / orb_high) - 1)*100:.2f}% (High: {max_high:.2f})")
            
            # Check if it hit stop loss (ORB low) after triggering long
            hit_sl = False
            for idx, row in after_trigger.iterrows():
                if float(row['Low']) < orb_low:
                    print(f"Hit Stop Loss (ORB Low) at {idx.strftime('%H:%M')}")
                    hit_sl = True
                    break
            if not hit_sl:
                print(f"Did not hit ORB Low SL.")
                
        elif broke_low_time:
            print(f"Broke ORB Low first at {broke_low_time.strftime('%H:%M')} (No LONG entry).")
        else:
            print("Never broke ORB High or Low (Choppy day).")
            
        # Overall day performance
        open_price = float(df.iloc[0]['Open'])
        close_price = float(df.iloc[-1]['Close'])
        print(f"Day % Change (Open to Close): {((close_price / open_price) - 1)*100:.2f}%")
        
    except Exception as e:
        print(f"Error: {e}")
