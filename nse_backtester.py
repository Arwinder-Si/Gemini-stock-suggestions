import requests
import datetime
from dateutil.relativedelta import relativedelta
import pandas as pd
import numpy as np
import vectorbt as vbt
import pandas_ta as ta
import plotly.graph_objects as go
import time
import yfinance as yf

def fetch_nse_data(symbol, start_date, end_date):
    """
    Fetches historical EOD data for a given symbol using yfinance as a fallback
    due to strict NSE 503 blocks on raw HTTP requests.
    """
    print(f"Fetching data for {symbol} from {start_date} to {end_date}...")
    
    # yfinance expects YYYY-MM-DD
    start_dt = datetime.datetime.strptime(start_date, "%d-%m-%Y").strftime("%Y-%m-%d")
    end_dt = datetime.datetime.strptime(end_date, "%d-%m-%Y").strftime("%Y-%m-%d")
    
    # Append .NS for NSE stocks in Yahoo Finance
    yf_symbol = f"{symbol}.NS"
    df = yf.download(yf_symbol, start=start_dt, end=end_dt, progress=False)
    
    if df.empty:
        print("No data fetched.")
        return pd.DataFrame()
        
    # Flatten MultiIndex columns if present (yfinance >= 0.2.0 might return MultiIndex)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        
    df.reset_index(inplace=True)
    
    # Rename columns to match what the script expects (lowercase)
    df.rename(columns={
        'Date': 'timestamp', 
        'Datetime': 'timestamp',
        'Open': 'open', 
        'High': 'high', 
        'Low': 'low', 
        'Close': 'close', 
        'Volume': 'volume'
    }, inplace=True)
    
    df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    df.set_index('timestamp', inplace=True)
    return df

def run_backtest():
    symbol = "RELIANCE"
    # Set date range (last 2 years for a solid backtest)
    end_date = datetime.datetime.now().strftime("%d-%m-%Y")
    start_date = (datetime.datetime.now() - relativedelta(years=2)).strftime("%d-%m-%Y")
    
    df = fetch_nse_data(symbol, start_date, end_date)
    if df.empty:
        print("Failed to acquire data. Aborting backtest.")
        return
        
    print(f"Acquired {len(df)} rows of data.")
    
    # --- Strategy 1: EMA Crossover ---
    fast_ema = vbt.MA.run(df['close'], 20)
    slow_ema = vbt.MA.run(df['close'], 50)
    ema_entries = fast_ema.ma_crossed_above(slow_ema)
    ema_exits = fast_ema.ma_crossed_below(slow_ema)

    # --- Strategy 2: RSI Mean Reversion ---
    rsi = vbt.RSI.run(df['close'], 14)
    rsi_entries = rsi.rsi_crossed_below(30)
    rsi_exits = rsi.rsi_crossed_above(70)

    # --- Strategy 3: Bollinger Band Breakout ---
    bbands = vbt.BBANDS.run(df['close'], 20, 2)
    bb_entries = df['close'] > bbands.upper
    bb_exits = df['close'] < bbands.lower

    # --- Strategy 4: Supertrend ---
    sti = ta.supertrend(df['high'], df['low'], df['close'], length=10, multiplier=3)
    # The direction column is the second column (index 1) in pandas_ta supertrend output
    st_dir = sti.iloc[:, 1]
    st_entries = (st_dir == 1) & (st_dir.shift(1) == -1)
    st_exits = (st_dir == -1) & (st_dir.shift(1) == 1)

    # Compile all signals into multi-column DataFrames
    entries = pd.DataFrame({
        'EMA Crossover': ema_entries,
        'RSI Reversion': rsi_entries,
        'BB Breakout': bb_entries,
        'Supertrend': st_entries,
        'Benchmark': False # Buy and hold has a single entry
    }, index=df.index)

    exits = pd.DataFrame({
        'EMA Crossover': ema_exits,
        'RSI Reversion': rsi_exits,
        'BB Breakout': bb_exits,
        'Supertrend': st_exits,
        'Benchmark': False # Benchmark never exits
    }, index=df.index)

    # Benchmark buys on first available day
    entries['Benchmark'].iloc[0] = True

    print("Running vectorbt portfolio simulation...")
    # Create Portfolio (Broadcasting across all strategies at once)
    pf = vbt.Portfolio.from_signals(
        df['close'], 
        entries=entries, 
        exits=exits, 
        init_cash=50000,           # Updated starting capital as requested
        fees=0.0015,               # 0.15% per trade (slippage + broker + STT)
        size=1.0,                  # 100% size
        size_type='percent',       # of available capital
        freq='D'                   # Daily frequency
    )

    # --- Performance Extraction ---
    metrics = []
    for strategy in entries.columns:
        s = pf[strategy].stats()
        metrics.append({
            'Strategy Name': strategy,
            'Total Return': s.get('Total Return [%]', np.nan),
            'Sharpe Ratio': s.get('Sharpe Ratio', np.nan),
            'Sortino Ratio': s.get('Sortino Ratio', np.nan),
            'Max Drawdown': s.get('Max Drawdown [%]', np.nan),
            'Win Rate': s.get('Win Rate [%]', np.nan),
            'Total Trades': s.get('Total Trades', np.nan),
            'Profit Factor': s.get('Profit Factor', np.nan)
        })
        
    metrics_df = pd.DataFrame(metrics)
    
    # Find the best strategy based on Total Return (excluding Benchmark for the title)
    best_strat = metrics_df[metrics_df['Strategy Name'] != 'Benchmark'].loc[metrics_df[metrics_df['Strategy Name'] != 'Benchmark']['Total Return'].idxmax()]
    best_name = best_strat['Strategy Name']
    best_return = best_strat['Total Return']
    
    # Save to CSV
    metrics_df.to_csv('strategy_comparison.csv', index=False)
    print(f"Saved comparison to strategy_comparison.csv")
    print("\n--- Strategy Comparison ---")
    print(metrics_df.to_string())
    
    # --- Plotting ---
    fig = pf.value().vbt.plot()
    # Apply dark theme and labels
    fig.update_layout(
        title=f"Strategy Equity Curves for {symbol}<br><sup>Best Strategy: {best_name} with {best_return:.2f}% return</sup>",
        xaxis_title="Date",
        yaxis_title="Portfolio Value (₹)",
        template="plotly_dark",
        hovermode="x unified",
        legend_title="Strategy"
    )
    
    # Save chart
    fig.write_image("equity_curves.png", width=1200, height=700)
    print("Saved equity curve plot to equity_curves.png")
    
    # Write summary
    print(f"\nBest Performing Strategy: {best_name}")
    print(f"Why it performed best: The {best_name} strategy captured the most favorable price action "
          f"for {symbol} over this period, overcoming the frictional costs (fees) better than the others. "
          f"Check the CSV and Plot to compare drawdown and win rates.")

if __name__ == "__main__":
    run_backtest()
