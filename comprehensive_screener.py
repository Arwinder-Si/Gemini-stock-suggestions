import sys
import io
import os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

"""
NSE Advanced Breakout Screener v3.0
====================================
Multi-factor SCORING system with empirical grounding.

v3 improvements over v2:
  1. Liquidity filter      — rejects stocks with < Rs.5cr avg daily traded value
  2. Overextension penalty — penalizes stocks already >8% above 20 EMA
  3. Market regime filter  — boosts/suppresses based on Nifty trend + VIX
  4. ATR-based consolidation — uses ATR contraction→expansion, not just range%
  5. Sector tagging        — shows sector concentration in output
  6. Explainable breakdown — prints per-factor score for each stock
  7. Non-linear scoring    — graduated curves instead of flat thresholds
"""

import yfinance as yf
import pandas as pd
import numpy as np
import warnings
import datetime
from clock import now_ist

warnings.filterwarnings('ignore')

# =============================================================================
# SECTOR MAP — hardcoded for the universe (faster than API calls)
# =============================================================================
SECTOR_MAP = {
    # IT
    'TCS': 'IT', 'INFY': 'IT', 'HCLTECH': 'IT', 'WIPRO': 'IT', 'TECHM': 'IT',
    'PERSISTENT': 'IT', 'COFORGE': 'IT', 'MPHASIS': 'IT', 'LTTS': 'IT',
    'TATAELXSI': 'IT', 'HAPPSTMNDS': 'IT', 'TANLA': 'IT',
    # Pharma
    'SUNPHARMA': 'Pharma', 'DRREDDY': 'Pharma', 'CIPLA': 'Pharma', 'LUPIN': 'Pharma',
    'DIVISLAB': 'Pharma', 'NATCOPHARM': 'Pharma', 'GLENMARK': 'Pharma',
    'AUROPHARMA': 'Pharma', 'BIOCON': 'Pharma', 'IPCALAB': 'Pharma',
    'LAURUSLABS': 'Pharma', 'ALKEM': 'Pharma', 'AJANTPHARM': 'Pharma',
    'GLAND': 'Pharma', 'ABBOTINDIA': 'Pharma', 'TORNTPHARM': 'Pharma',
    'MANKIND': 'Pharma',
    # Banking / Financial
    'HDFCBANK': 'Banking', 'ICICIBANK': 'Banking', 'SBIN': 'Banking',
    'KOTAKBANK': 'Banking', 'AXISBANK': 'Banking', 'PNB': 'Banking',
    'BANKBARODA': 'Banking', 'FEDERALBNK': 'Banking', 'IDFCFIRSTB': 'Banking',
    'AUBANK': 'Banking', 'BANDHANBNK': 'Banking', 'INDIANB': 'Banking',
    'BAJFINANCE': 'NBFC', 'BAJAJFINSV': 'NBFC', 'CHOLAFIN': 'NBFC',
    'MUTHOOTFIN': 'NBFC', 'MANAPPURAM': 'NBFC', 'LICHSGFIN': 'NBFC',
    'SBILIFE': 'Insurance', 'HDFCLIFE': 'Insurance', 'ICICIPRULI': 'Insurance',
    'PFC': 'NBFC', 'RECLTD': 'NBFC',
    # Auto
    'MARUTI': 'Auto', 'M&M': 'Auto', 'BAJAJ-AUTO': 'Auto', 'EICHERMOT': 'Auto',
    'TVSMOTOR': 'Auto', 'ASHOKLEY': 'Auto', 'MOTHERSON': 'Auto',
    'SONACOMS': 'Auto', 'EXIDEIND': 'Auto', 'BHARATFORG': 'Auto',
    'APOLLOTYRE': 'Auto', 'BALKRISIND': 'Auto',
    # FMCG / Consumer
    'HINDUNILVR': 'FMCG', 'ITC': 'FMCG', 'NESTLEIND': 'FMCG',
    'BRITANNIA': 'FMCG', 'GODREJCP': 'FMCG', 'MARICO': 'FMCG',
    'DABUR': 'FMCG', 'COLPAL': 'FMCG', 'EMAMILTD': 'FMCG',
    'TATACONSUM': 'FMCG', 'PAGEIND': 'FMCG', 'BATAINDIA': 'FMCG',
    # Energy / Power
    'RELIANCE': 'Energy', 'ONGC': 'Energy', 'IOC': 'Energy', 'BPCL': 'Energy',
    'GAIL': 'Energy', 'COALINDIA': 'Energy',
    'NTPC': 'Power', 'POWERGRID': 'Power', 'TATAPOWER': 'Power',
    'ADANIGREEN': 'Power', 'ADANIPOWER': 'Power', 'TORNTPOWER': 'Power',
    'CESC': 'Power', 'NHPC': 'Power', 'SJVN': 'Power',
    # Metals / Materials
    'TATASTEEL': 'Metals', 'JSWSTEEL': 'Metals', 'HINDALCO': 'Metals',
    'JINDALSTEL': 'Metals', 'HINDZINC': 'Metals', 'JSL': 'Metals',
    # Chemicals
    'PIIND': 'Chemicals', 'AARTIIND': 'Chemicals', 'DEEPAKNTR': 'Chemicals',
    'CLEAN': 'Chemicals', 'FLUOROCHEM': 'Chemicals', 'SRF': 'Chemicals',
    # Infrastructure / Capital Goods
    'LT': 'Infra', 'SIEMENS': 'Infra', 'ABB': 'Infra', 'HAL': 'Defence',
    'BEL': 'Defence', 'BDL': 'Defence', 'COCHINSHIP': 'Defence',
    'GRSE': 'Defence', 'MAZDOCK': 'Defence',
    'RITES': 'Infra', 'IRCTC': 'Infra', 'RVNL': 'Infra', 'IRFC': 'Infra',
    'NBCC': 'Infra', 'HUDCO': 'Infra',
    'CUMMINSIND': 'Cap Goods', 'THERMAX': 'Cap Goods', 'HAVELLS': 'Cap Goods',
    'CROMPTON': 'Cap Goods', 'BLUESTARCO': 'Cap Goods', 'VOLTAS': 'Cap Goods',
    'POLYCAB': 'Cap Goods', 'KEI': 'Cap Goods',
    # Tech / New-age
    'DELHIVERY': 'New-Age', 'NYKAA': 'New-Age', 'PAYTM': 'New-Age',
    'POLICYBZR': 'New-Age', 'DIXON': 'Electronics', 'KAYNES': 'Electronics',
    'AFFLE': 'Electronics', 'CGPOWER': 'Electronics',
    # Cement / Construction
    'ULTRACEMCO': 'Cement', 'SHREECEM': 'Cement', 'AMBUJACEM': 'Cement',
    'DLF': 'Realty', 'PHOENIXLTD': 'Realty',
    # Retail
    'TRENT': 'Retail', 'DMART': 'Retail', 'JUBLFOOD': 'Retail',
    # Conglomerates
    'ADANIENT': 'Conglomerate', 'ADANIPORTS': 'Conglomerate',
    'TITAN': 'Consumer', 'ASIANPAINT': 'Consumer', 'PIDILITIND': 'Consumer',
    'BOSCHLTD': 'Auto', 'MRF': 'Auto', 'GRASIM': 'Diversified',
    'BHARTIARTL': 'Telecom',
    'VBL': 'FMCG',
    # ── Small Cap Sectors ──
    'HIRECT': 'Electronics', 'NUVOCO': 'Cement', 'HFCL': 'Telecom', 'ITDC': 'Tourism',
    'ZENITHEXPO': 'Infra', 'SUZLON': 'Power',
    'RPOWER': 'Power', 'GTLINFRA': 'Telecom',
    'IDEA': 'Telecom', 'YESBANK': 'Banking', 'UCOBANK': 'Banking', 'IOB': 'Banking',
    'CENTRALBK': 'Banking', 'BANKINDIA': 'Banking', 'MAHABANK': 'Banking',
    'PSB': 'Banking', 'J&KBANK': 'Banking', 'SOUTHBANK': 'Banking',
    'KARURVYSYA': 'Banking', 'EQUITASBNK': 'Banking', 'UJJIVANSFB': 'Banking',
    'SURYODAY': 'Banking', 'ESAFSFB': 'Banking',
    'IRB': 'Infra', 'HCC': 'Infra', 'TRIDENT': 'Textile',
    'VAKRANGEE': 'IT', 'PCJEWELLER': 'Consumer', 'ALOKINDS': 'Textile',
    'GVKPIL': 'Infra', 'RCOM': 'Telecom',
    'AWL': 'FMCG', 'NDTV': 'Media', 'BSE': 'Financial Services',
    'CDSL': 'Financial Services', 'CAMS': 'Financial Services',
    'ANGELONE': 'Financial Services', 'MOTILALOFS': 'Financial Services',
    'UTIAMC': 'Financial Services', 'NAM-INDIA': 'Financial Services',
    'KPITTECH': 'IT', 'PERSISTENT': 'IT', 'PAYTM': 'New-Age',
    'DELHIVERY': 'New-Age', 'POLICYBZR': 'New-Age', 'NYKAA': 'New-Age',
    'TATAELXSI': 'IT', 'COFORGE': 'IT',
    'RVNL': 'Infra', 'IRFC': 'Infra', 'RAILTEL': 'Telecom',
    'HUDCO': 'Infra', 'IREDA': 'NBFC', 'COCHINSHIP': 'Defence', 'GRSE': 'Defence',
    'JETAIRWAYS': 'Aviation',
}

# =============================================================================
# STOCK UNIVERSE
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

SMALL_CAP = [
    # User-requested stocks
    'HIRECT', 'NUVOCO', 'HFCL', 'ITDC',
    # Power / Energy
    'SUZLON', 'RPOWER', 'ADANIPOWER', 'ADANIGREEN',
    # Banking (small PSU + SFBs)
    'YESBANK', 'UCOBANK', 'IOB', 'CENTRALBK', 'BANKINDIA',
    'MAHABANK', 'PSB', 'J&KBANK', 'SOUTHBANK', 'KARURVYSYA',
    'EQUITASBNK', 'UJJIVANSFB', 'SURYODAY', 'ESAFSFB',
    # Infra / Construction
    'IRB', 'HCC', 'RVNL', 'HUDCO', 'IRFC', 'RAILTEL',
    # Defence
    'COCHINSHIP', 'GRSE',
    # IT / Tech (small cap)
    'KPITTECH', 'PERSISTENT', 'TATAELXSI', 'COFORGE',
    # New-Age / Fintech
    'PAYTM', 'DELHIVERY', 'POLICYBZR', 'NYKAA',
    # Financial Services
    'BSE', 'CDSL', 'CAMS', 'ANGELONE', 'MOTILALOFS', 'UTIAMC', 'NAM-INDIA',
    # Consumer / Textile / Media
    'AWL', 'NDTV', 'TRIDENT', 'IREDA',
    # Telecom
    'IDEA', 'ZENITHEXPO',
]

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--universe", choices=["large", "small"], default="large")
args, unknown = parser.parse_known_args()

if args.universe == "small":
    all_tickers_list = list(dict.fromkeys(SMALL_CAP))
    out_file = "screener_results_smallcap.csv"
else:
    all_tickers_list = list(dict.fromkeys(NIFTY_LARGE + NIFTY_MIDCAP))
    out_file = "screener_results.csv"

all_tickers = [t + ".NS" for t in all_tickers_list]

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def compute_rsi(series, period=14):
    """Compute RSI using exponential moving average method."""
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=period - 1, adjust=False).mean()
    ema_down = down.ewm(com=period - 1, adjust=False).mean()
    rs = ema_up / ema_down
    return 100 - (100 / (1 + rs))


def compute_atr(high, low, close, period=14):
    """Compute Average True Range."""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def get_market_regime(nifty_close):
    """
    Determine market regime based on Nifty 50 position vs its 200 EMA.
    Returns a regime string and a score modifier (-10 to +10).
    """
    if len(nifty_close) < 200:
        return "UNKNOWN", 0

    ema_200 = nifty_close.ewm(span=200, adjust=False).mean().iloc[-1]
    ema_50 = nifty_close.ewm(span=50, adjust=False).mean().iloc[-1]
    current = nifty_close.iloc[-1]

    if current > ema_200 and current > ema_50:
        return "BULLISH", 10
    elif current > ema_200:
        return "NEUTRAL-BULL", 5
    elif current < ema_200 and current < ema_50:
        return "BEARISH", -10
    else:
        return "NEUTRAL-BEAR", -5


# =============================================================================
# MAIN SCREENER
# =============================================================================

def run_screener():
    print("=" * 70)
    print(f"  NSE ADVANCED BREAKOUT SCREENER v3.0")
    print(f"  Scanning {len(all_tickers)} stocks | {now_ist().strftime('%d-%b-%Y %H:%M')}")
    print("=" * 70)

    # --- Download data ---
    print(f"\nDownloading 1 year of daily data for {len(all_tickers)} stocks...")
    data = yf.download(all_tickers, period="1y", interval="1d", progress=True)

    # If run during market hours, the last row is an incomplete daily candle. Drop it.
    now = now_ist()
    if not data.empty and data.index[-1].date() == now.date() and now.time() < datetime.time(15, 30):
        print("  [Note] Market is still open. Excluding today's incomplete daily candle.")
        data = data.iloc[:-1]

    # Nifty 50 for relative strength and regime
    nifty_data = yf.download("^NSEI", period="1y", interval="1d", progress=False)
    if isinstance(nifty_data.columns, pd.MultiIndex):
        nifty_close = nifty_data['Close'].iloc[:, 0].dropna()
    else:
        nifty_close = nifty_data['Close'].dropna()

    nifty_10d_return = (nifty_close.iloc[-1] / nifty_close.iloc[-10] - 1) * 100

    # --- Market Regime ---
    regime, regime_modifier = get_market_regime(nifty_close)
    print(f"\n  Market Regime: {regime} (score modifier: {regime_modifier:+d})")
    with open("market_regime.txt", "w") as f:
        f.write(regime)

    # --- Fetch India VIX ---
    vix_data = yf.download("^INDIAVIX", period="5d", interval="1d", progress=False)
    if not vix_data.empty:
        if isinstance(vix_data.columns, pd.MultiIndex):
            vix_val = vix_data['Close'].iloc[-1, 0]
        else:
            vix_val = vix_data['Close'].iloc[-1]
        vix_modifier = 5 if vix_val < 15 else (0 if vix_val < 20 else -5)
        print(f"  India VIX: {vix_val:.1f} (score modifier: {vix_modifier:+d})")
    else:
        vix_val = None
        vix_modifier = 0
        print("  India VIX: unavailable")

    total_env_modifier = regime_modifier + vix_modifier
    print(f"  Combined environment modifier: {total_env_modifier:+d}")

    # --- Load News Features ---
    news_df = pd.DataFrame()
    if os.path.exists('news_features.csv'):
        try:
            news_df = pd.read_csv('news_features.csv').set_index('symbol')
            print(f"  Loaded news features for {len(news_df)} stocks.")
        except Exception as e:
            print(f"  Error loading news features: {e}")
    else:
        print("  News features not found. Running pure technicals.")

from scoring import score_stock, ScoreInput

    # --- Score each stock ---
    results = []

    for ticker in all_tickers:
        try:
            close = data['Close'][ticker].dropna()
            volume = data['Volume'][ticker].dropna()
            high = data['High'][ticker].dropna()
            low = data['Low'][ticker].dropna()

            name = ticker.replace('.NS', '')
            
            sentiment_7d = 0.0
            has_reg_risk = False
            if not news_df.empty and name in news_df.index:
                news_row = news_df.loc[name]
                sentiment_7d = float(news_row.get('sentiment_7d', 0.0))
                has_reg_risk = bool(news_row.get('has_neg_reg_news_7d', False))

            inp = ScoreInput(
                symbol=name,
                close=close,
                high=high,
                low=low,
                volume=volume,
                nifty_10d_return=nifty_10d_return,
                total_env_modifier=total_env_modifier,
                universe=args.universe,
                sentiment_7d=sentiment_7d,
                has_reg_risk=has_reg_risk,
            )

            res = score_stock(inp)

            if res.passed_filters:
                current_close = close.iloc[-1]
                ema_20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
                dist_from_ema20_pct = (current_close - ema_20) / ema_20 * 100
                sector = SECTOR_MAP.get(name, 'Other')
                results.append({
                    'Stock': name,
                    'Sector': sector,
                    'Close': res.current_close,
                    'Score': res.score,
                    'Vol_Ratio': res.vol_ratio,
                    'RSI': res.rsi_val,
                    'Liq_Cr': res.avg_traded_value_cr,
                    'Dist_EMA20': round(float(dist_from_ema20_pct), 1),
                    'Breakdown': res.factor_breakdown,
                    'Penalties': res.penalties,
                })

        except Exception as e:
            pass

    # =========================================================================
    # OUTPUT
    # =========================================================================
    if not results:
        print("\nNo stocks scored above 50/100 today.")
        empty_df = pd.DataFrame(columns=['Stock', 'Sector', 'Close', 'Score', 'Vol_Ratio', 'RSI', 'Liq_Cr', 'Dist_EMA20'])
        empty_df.to_csv(out_file, index=False)
        print(f"Empty results written to {out_file}.")
        return

    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values('Score', ascending=False).reset_index(drop=True)
    results_df.index += 1

    print(f"\n{'=' * 70}")
    print(f"  TOP BREAKOUT CANDIDATES - Ranked by Composite Score (out of 100)")
    vix_str = f"{vix_val:.1f}" if vix_val else "N/A"
    print(f"  Regime: {regime} | VIX: {vix_str} | Env modifier: {total_env_modifier:+d}")
    print(f"{'=' * 70}")

    # Print top 15 with full breakdown
    top = results_df.head(15)
    for _, row in top.iterrows():
        print(f"\n  #{_:2d}  {row['Stock']:<15s}  Rs.{row['Close']:>10,.2f}   "
              f"Score: {row['Score']:3d}/100   [{row['Sector']}]")
        print(f"       Liq: Rs.{row['Liq_Cr']:.0f}cr/day | Vol: {row['Vol_Ratio']}x | "
              f"RSI: {int(row['RSI'])} | Dist 20EMA: {row['Dist_EMA20']:+.1f}%")

        # Explainable breakdown
        bd = row['Breakdown']
        parts = []
        for factor, (pts, explanation) in bd.items():
            if pts > 0:
                parts.append(f"+{pts} {factor} ({explanation})")
        print(f"       Score: {' | '.join(parts)}")

        if row['Penalties']:
            print(f"       Penalties: {' | '.join(row['Penalties'])}")

    # --- Sector concentration ---
    print(f"\n{'=' * 70}")
    print(f"  SECTOR DISTRIBUTION")
    print(f"{'=' * 70}")
    sector_counts = results_df['Sector'].value_counts()
    for sector, count in sector_counts.items():
        bar = '#' * count
        print(f"  {sector:<15s} {count:2d} {bar}")

    total_scored = len(results_df)
    if sector_counts.iloc[0] / total_scored > 0.5:
        top_sector = sector_counts.index[0]
        print(f"\n  WARNING: >50% concentration in {top_sector} - consider diversification")

    # Save CSV (without breakdown dict for clean export)
    export_df = results_df.drop(columns=['Breakdown', 'Penalties'])
    export_df.to_csv(out_file, index=True)
    print(f"\nFull results saved to {out_file} ({len(results_df)} stocks)")


if __name__ == "__main__":
    run_screener()
