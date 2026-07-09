import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

"""
Screener Historical Backtest
==============================
Runs the v3 scoring engine over every trading day in the past year and
measures actual forward returns for each score bucket.

This is the empirical proof that higher scores = better trades.
If they don't, we adjust the weights until they do.
"""

import yfinance as yf
import pandas as pd
import numpy as np
import warnings
import datetime

warnings.filterwarnings('ignore')

# =============================================================================
# STOCK UNIVERSE (same as comprehensive_screener.py)
# =============================================================================
NIFTY_LARGE = [
    'RELIANCE', 'TCS', 'HDFCBANK', 'ICICIBANK', 'BHARTIARTL', 'SBIN', 'INFY',
    'ITC', 'HINDUNILVR', 'LT', 'BAJFINANCE', 'HCLTECH', 'MARUTI',
    'SUNPHARMA', 'ADANIENT', 'KOTAKBANK', 'TITAN', 'ONGC',
    'NTPC', 'AXISBANK', 'DMART', 'ADANIPORTS', 'ULTRACEMCO',
    'ASIANPAINT', 'COALINDIA', 'BAJAJFINSV', 'BAJAJ-AUTO', 'POWERGRID',
    'NESTLEIND', 'WIPRO', 'M&M', 'IOC', 'HAL', 'DLF',
    'JSWSTEEL', 'TATASTEEL', 'SIEMENS', 'IRFC', 'PIDILITIND',
    'GRASIM', 'SBILIFE', 'BEL', 'TRENT', 'PNB', 'INDIGO', 'BANKBARODA',
    'HDFCLIFE', 'ABB', 'BPCL', 'PFC', 'GODREJCP', 'TATAPOWER', 'HINDALCO',
    'AMBUJACEM', 'CHOLAFIN', 'HINDZINC', 'BOSCHLTD', 'RECLTD',
    'GAIL', 'TVSMOTOR', 'ICICIPRULI', 'DIVISLAB', 'SHREECEM',
    'TECHM', 'EICHERMOT', 'BRITANNIA', 'SRF', 'CGPOWER',
    'JINDALSTEL', 'TORNTPHARM', 'MRF', 'MARICO', 'MANKIND',
]

NIFTY_MIDCAP = [
    'NATCOPHARM', 'GLENMARK', 'AUROPHARMA', 'BIOCON', 'IPCALAB',
    'LAURUSLABS', 'ALKEM', 'AJANTPHARM', 'GLAND', 'DRREDDY',
    'LUPIN', 'CIPLA', 'ABBOTINDIA',
    'RITES', 'IRCTC', 'RVNL', 'NHPC', 'SJVN', 'NBCC', 'BDL', 'PHOENIXLTD',
    'HUDCO', 'COCHINSHIP', 'GRSE', 'MAZDOCK',
    'PERSISTENT', 'COFORGE', 'MPHASIS', 'LTTS', 'TATAELXSI',
    'HAPPSTMNDS', 'TANLA',
    'DELHIVERY', 'NYKAA', 'PAYTM', 'POLICYBZR',
    'TATACONSUM', 'COLPAL', 'DABUR', 'EMAMILTD', 'JUBLFOOD',
    'PAGEIND', 'BATAINDIA', 'VOLTAS',
    'MOTHERSON', 'SONACOMS', 'EXIDEIND', 'BHARATFORG',
    'APOLLOTYRE', 'BALKRISIND', 'ASHOKLEY',
    'MUTHOOTFIN', 'MANAPPURAM', 'LICHSGFIN', 'FEDERALBNK',
    'IDFCFIRSTB', 'AUBANK', 'BANDHANBNK', 'INDIANB',
    'CUMMINSIND', 'THERMAX', 'KAYNES', 'AFFLE', 'DIXON',
    'POLYCAB', 'KEI', 'HAVELLS', 'CROMPTON', 'BLUESTARCO',
    'PIIND', 'AARTIIND', 'DEEPAKNTR', 'CLEAN', 'FLUOROCHEM',
    'ADANIGREEN', 'ADANIPOWER', 'TATAPOWER', 'TORNTPOWER', 'CESC', 'JSL',
]

all_tickers_list = list(dict.fromkeys(NIFTY_LARGE + NIFTY_MIDCAP))
all_tickers = [t + ".NS" for t in all_tickers_list]


# =============================================================================
# HELPER FUNCTIONS (same as screener v3)
# =============================================================================

def compute_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=period - 1, adjust=False).mean()
    ema_down = down.ewm(com=period - 1, adjust=False).mean()
    rs = ema_up / ema_down
    return 100 - (100 / (1 + rs))


def compute_atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def score_stock_on_day(close_series, volume_series, high_series, low_series,
                       day_idx, nifty_close_series, nifty_day_idx):
    """
    Compute the v3 score for a single stock on a single day.
    Uses only data available up to and including day_idx (no lookahead).
    Returns the score (int) or None if the stock should be filtered out.
    """
    # Need at least 60 bars of history before this day
    if day_idx < 60:
        return None

    close = close_series.iloc[:day_idx + 1]
    volume = volume_series.iloc[:day_idx + 1]
    high = high_series.iloc[:day_idx + 1]
    low = low_series.iloc[:day_idx + 1]

    current_close = close.iloc[-1]
    if current_close < 50:
        return None

    # Liquidity filter
    avg_price_20 = close.iloc[-20:].mean()
    avg_vol_20 = volume.iloc[-20:].mean()
    avg_traded_value_cr = (avg_price_20 * avg_vol_20) / 1e7
    if avg_traded_value_cr < 5:
        return None

    score = 0

    # Factor 1: Volume surge
    today_vol = volume.iloc[-1]
    vol_ratio = today_vol / avg_vol_20 if avg_vol_20 > 0 else 0
    if vol_ratio >= 3.0:
        score += 20
    elif vol_ratio >= 2.0:
        score += 15
    elif vol_ratio >= 1.5:
        score += 10
    elif vol_ratio >= 1.2:
        score += 5

    # Factor 2: ATR consolidation breakout
    atr = compute_atr(high, low, close, 14)
    if len(atr.dropna()) >= 20:
        current_atr = atr.iloc[-1]
        avg_atr_prev = atr.iloc[-21:-1].mean()
        atr_ratio = current_atr / avg_atr_prev if avg_atr_prev > 0 else 1
        high_20 = close.iloc[-21:-1].max()
        broke_above = current_close > high_20

        if broke_above and atr_ratio >= 1.5:
            score += 20
        elif broke_above and atr_ratio >= 1.2:
            score += 15
        elif broke_above:
            score += 10
        elif atr_ratio >= 1.5:
            score += 5

    # Factor 3: Relative strength vs Nifty
    nifty_slice = nifty_close_series.iloc[:nifty_day_idx + 1]
    if len(close) >= 10 and len(nifty_slice) >= 10:
        stock_10d = (close.iloc[-1] / close.iloc[-10] - 1) * 100
        nifty_10d = (nifty_slice.iloc[-1] / nifty_slice.iloc[-10] - 1) * 100
        rs_diff = stock_10d - nifty_10d
        if rs_diff >= 5:
            score += 20
        elif rs_diff >= 3:
            score += 15
        elif rs_diff >= 1:
            score += 10
        elif rs_diff >= 0:
            score += 5

    # Factor 4: EMA trend alignment
    ema_10 = close.ewm(span=10, adjust=False).mean().iloc[-1]
    ema_20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema_50 = close.ewm(span=50, adjust=False).mean().iloc[-1]

    if current_close > ema_10 > ema_20 > ema_50:
        score += 20
    elif current_close > ema_20 > ema_50:
        score += 15
    elif current_close > ema_50:
        score += 10
    elif current_close > ema_20:
        score += 5

    # Factor 5: RSI
    rsi = compute_rsi(close, 14)
    rsi_val = rsi.iloc[-1]
    if 55 <= rsi_val <= 70:
        score += 20
    elif 50 <= rsi_val < 55:
        score += 15
    elif 40 <= rsi_val < 50:
        score += 10
    elif rsi_val > 70:
        score += 5

    # Penalty: Overextension
    dist_from_ema20 = (current_close - ema_20) / ema_20 * 100
    if dist_from_ema20 > 12:
        score -= 15
    elif dist_from_ema20 > 8:
        score -= 10
    elif dist_from_ema20 > 5:
        score -= 5

    # Penalty: Low volume on breakout
    if score >= 40 and vol_ratio < 1.0:
        score -= 15

    return max(0, min(100, score))


# =============================================================================
# MAIN BACKTEST
# =============================================================================

def run_backtest():
    print("=" * 70)
    print("  SCREENER HISTORICAL BACKTEST")
    print("  Testing if higher scores predict better forward returns")
    print("=" * 70)

    # Download 2 years of data (1yr lookback + 1yr for forward returns)
    print(f"\nDownloading 2 years of data for {len(all_tickers)} stocks...")
    data = yf.download(all_tickers, period="2y", interval="1d", progress=True)

    nifty_data = yf.download("^NSEI", period="2y", interval="1d", progress=False)
    if isinstance(nifty_data.columns, pd.MultiIndex):
        nifty_close = nifty_data['Close'].iloc[:, 0].dropna()
    else:
        nifty_close = nifty_data['Close'].dropna()

    # We'll test on the last ~200 trading days (roughly 10 months)
    # Starting from day 260 (to have 60 days of lookback + 200 days of ATR history)
    # and ending 10 days before the last day (so we can measure 10-day forward returns)

    # Get common date index
    dates = data['Close'].dropna(how='all').index
    nifty_dates = nifty_close.index

    # Ensure we have enough history
    start_test_idx = 260  # need 260 days of history before first test day
    end_test_idx = len(dates) - 11  # need 10 forward trading days

    if end_test_idx <= start_test_idx:
        print("Not enough data to run backtest. Need at least 270 trading days.")
        return

    print(f"\nBacktesting from day {start_test_idx} to {end_test_idx} "
          f"({end_test_idx - start_test_idx} trading days)")

    all_signals = []  # list of dicts: date, stock, score, fwd_ret_3d, fwd_ret_5d, fwd_ret_10d

    test_days = list(range(start_test_idx, end_test_idx + 1))
    total_days = len(test_days)

    for progress_i, day_idx in enumerate(test_days):
        if progress_i % 20 == 0:
            print(f"  Processing day {progress_i}/{total_days}...")

        signal_date = dates[day_idx]

        # Find the corresponding nifty day index
        try:
            pos = nifty_dates.searchsorted(signal_date, side='right') - 1
            if pos < 10:
                continue
            nifty_day_idx = pos
        except Exception:
            continue

        for ticker in all_tickers:
            try:
                close = data['Close'][ticker].dropna()
                volume = data['Volume'][ticker].dropna()
                high_s = data['High'][ticker].dropna()
                low_s = data['Low'][ticker].dropna()

                # Find this day's index in the stock's own series
                if signal_date not in close.index:
                    continue
                stock_day_idx = close.index.get_loc(signal_date)

                score = score_stock_on_day(
                    close, volume, high_s, low_s,
                    stock_day_idx, nifty_close, nifty_day_idx
                )

                if score is None or score < 50:
                    continue

                # Measure forward returns (no lookahead — using next-day open onwards)
                entry_price = close.iloc[stock_day_idx]  # signal day close (entry)

                # 3-day, 5-day, 10-day forward returns
                fwd_3 = fwd_5 = fwd_10 = np.nan

                if stock_day_idx + 3 < len(close):
                    fwd_3 = (close.iloc[stock_day_idx + 3] / entry_price - 1) * 100

                if stock_day_idx + 5 < len(close):
                    fwd_5 = (close.iloc[stock_day_idx + 5] / entry_price - 1) * 100

                if stock_day_idx + 10 < len(close):
                    fwd_10 = (close.iloc[stock_day_idx + 10] / entry_price - 1) * 100

                # Max Adverse Excursion (MAE) — worst drawdown in next 5 days
                mae = 0
                if stock_day_idx + 5 < len(close):
                    fwd_lows = close.iloc[stock_day_idx + 1: stock_day_idx + 6]
                    min_price = fwd_lows.min()
                    mae = (min_price / entry_price - 1) * 100

                all_signals.append({
                    'date': signal_date,
                    'stock': ticker.replace('.NS', ''),
                    'score': score,
                    'entry_price': round(entry_price, 2),
                    'fwd_ret_3d': round(fwd_3, 2) if not np.isnan(fwd_3) else np.nan,
                    'fwd_ret_5d': round(fwd_5, 2) if not np.isnan(fwd_5) else np.nan,
                    'fwd_ret_10d': round(fwd_10, 2) if not np.isnan(fwd_10) else np.nan,
                    'mae_5d': round(mae, 2),
                })

            except Exception:
                pass

    if not all_signals:
        print("No signals generated during backtest period.")
        return

    signals_df = pd.DataFrame(all_signals)
    print(f"\nTotal signals generated: {len(signals_df)}")

    # ==========================================================================
    # ANALYSIS BY SCORE BUCKET
    # ==========================================================================

    # Define buckets
    bins = [49, 59, 69, 79, 89, 100]
    labels = ['50-59', '60-69', '70-79', '80-89', '90-100']
    signals_df['bucket'] = pd.cut(signals_df['score'], bins=bins, labels=labels)

    print(f"\n{'=' * 80}")
    print(f"  RESULTS BY SCORE BUCKET")
    print(f"{'=' * 80}")
    print(f"\n  {'Bucket':<10s} {'Signals':>8s} {'Hit 3d':>8s} {'Hit 5d':>8s} "
          f"{'Avg 3d':>8s} {'Avg 5d':>8s} {'Avg 10d':>8s} {'Avg MAE':>8s} {'PF 5d':>8s}")
    print(f"  {'-' * 74}")

    for bucket in labels:
        subset = signals_df[signals_df['bucket'] == bucket]
        if len(subset) == 0:
            continue

        n = len(subset)
        hit_3d = (subset['fwd_ret_3d'] > 0).sum() / len(subset.dropna(subset=['fwd_ret_3d'])) * 100 \
            if len(subset.dropna(subset=['fwd_ret_3d'])) > 0 else 0
        hit_5d = (subset['fwd_ret_5d'] > 0).sum() / len(subset.dropna(subset=['fwd_ret_5d'])) * 100 \
            if len(subset.dropna(subset=['fwd_ret_5d'])) > 0 else 0

        avg_3d = subset['fwd_ret_3d'].mean()
        avg_5d = subset['fwd_ret_5d'].mean()
        avg_10d = subset['fwd_ret_10d'].mean()
        avg_mae = subset['mae_5d'].mean()

        # Profit factor for 5d returns
        wins = subset[subset['fwd_ret_5d'] > 0]['fwd_ret_5d'].sum()
        losses = abs(subset[subset['fwd_ret_5d'] < 0]['fwd_ret_5d'].sum())
        pf = wins / losses if losses > 0 else float('inf')

        print(f"  {bucket:<10s} {n:>8d} {hit_3d:>7.1f}% {hit_5d:>7.1f}% "
              f"{avg_3d:>+7.2f}% {avg_5d:>+7.2f}% {avg_10d:>+7.2f}% "
              f"{avg_mae:>+7.2f}% {pf:>8.2f}")

    # Save full signal log
    signals_df.to_csv('screener_backtest_log.csv', index=False)
    print(f"\nFull signal log saved to screener_backtest_log.csv")

    # Quick validation
    high_score = signals_df[signals_df['score'] >= 80]['fwd_ret_5d'].mean()
    low_score = signals_df[signals_df['score'] < 70]['fwd_ret_5d'].mean()

    print(f"\n{'=' * 80}")
    print(f"  VALIDATION")
    print(f"{'=' * 80}")
    if not np.isnan(high_score) and not np.isnan(low_score):
        if high_score > low_score:
            print(f"\n  PASS: High-score signals (>=80) avg 5d return: {high_score:+.2f}%")
            print(f"        Low-score signals (<70)  avg 5d return: {low_score:+.2f}%")
            print(f"        Differential: {high_score - low_score:+.2f}% -- scoring system works!")
        else:
            print(f"\n  FAIL: High-score signals (>=80) avg 5d return: {high_score:+.2f}%")
            print(f"        Low-score signals (<70)  avg 5d return: {low_score:+.2f}%")
            print(f"        Scoring needs weight adjustment!")
    else:
        print("\n  Insufficient data for validation.")


if __name__ == "__main__":
    run_backtest()
