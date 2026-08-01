"""
Unified stock scoring module for screener and backtesting.
Provides score_stock() to evaluate a single stock based on price/volume history and environment factors.
"""

from dataclasses import dataclass, field
import pandas as pd


@dataclass
class ScoreInput:
    symbol: str
    close: pd.Series
    high: pd.Series
    low: pd.Series
    volume: pd.Series
    nifty_10d_return: float = 0.0
    total_env_modifier: int = 0
    universe: str = "large"  # "large" or "small"
    sentiment_7d: float = 0.0
    has_reg_risk: bool = False


@dataclass
class ScoreResult:
    symbol: str
    score: int
    passed_filters: bool
    current_close: float
    vol_ratio: float
    rsi_val: float
    avg_traded_value_cr: float
    factor_breakdown: dict[str, tuple[int, str]] = field(default_factory=dict)
    penalties: list[str] = field(default_factory=list)


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI using exponential moving average method."""
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=period - 1, adjust=False).mean()
    ema_down = down.ewm(com=period - 1, adjust=False).mean()
    rs = ema_up / ema_down
    return 100 - (100 / (1 + rs))


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Compute Average True Range."""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def score_stock(inp: ScoreInput) -> ScoreResult:
    """
    Score a stock out of 100 based on 5 technical factors, penalties, environment modifiers, and news.
    """
    close = inp.close.dropna()
    volume = inp.volume.dropna()
    high = inp.high.dropna()
    low = inp.low.dropna()

    empty_result = ScoreResult(
        symbol=inp.symbol, score=0, passed_filters=False,
        current_close=0.0, vol_ratio=0.0, rsi_val=0.0, avg_traded_value_cr=0.0
    )

    if len(close) < 60 or len(volume) < 60:
        return empty_result

    current_close = close.iloc[-1]

    # Penny stock check
    penny_floor = 100 if inp.universe == "small" else 50
    if current_close < penny_floor:
        return empty_result

    # Liquidity check
    avg_price_20 = close.iloc[-20:].mean()
    avg_vol_20 = volume.iloc[-20:].mean()
    avg_traded_value_cr = (avg_price_20 * avg_vol_20) / 1e7

    liq_threshold = 1.0 if inp.universe == "small" else 5.0
    if avg_traded_value_cr < liq_threshold:
        return empty_result

    score = 0
    breakdown = {}
    penalties = []

    # --- Factor 1: Volume Surge ---
    today_vol = volume.iloc[-1]
    vol_ratio = today_vol / avg_vol_20 if avg_vol_20 > 0 else 0.0

    if vol_ratio >= 3.0:
        pts = 20
    elif vol_ratio >= 2.0:
        pts = 15
    elif vol_ratio >= 1.5:
        pts = 10
    elif vol_ratio >= 1.2:
        pts = 5
    else:
        pts = 0
    score += pts
    breakdown['Volume'] = (pts, f"{vol_ratio:.1f}x avg")

    # --- Factor 2: Consolidation Breakout via ATR ---
    atr = compute_atr(high, low, close, 14)
    if len(atr.dropna()) >= 20:
        current_atr = atr.iloc[-1]
        avg_atr_prev = atr.iloc[-21:-1].mean()
        atr_ratio = current_atr / avg_atr_prev if avg_atr_prev > 0 else 1.0

        high_20 = close.iloc[-21:-1].max()
        broke_above = current_close > high_20

        if broke_above and atr_ratio >= 1.5:
            pts = 20
            tag = f"ATR expansion {atr_ratio:.1f}x + 20d high break"
        elif broke_above and atr_ratio >= 1.2:
            pts = 15
            tag = f"ATR expansion {atr_ratio:.1f}x + 20d high break"
        elif broke_above:
            pts = 10
            tag = "20d high break"
        elif atr_ratio >= 1.5:
            pts = 5
            tag = f"ATR expanding {atr_ratio:.1f}x (no price break yet)"
        else:
            pts = 0
            tag = "No breakout"
    else:
        pts = 0
        tag = "Insufficient ATR data"

    score += pts
    breakdown['Consolidation'] = (pts, tag)

    # --- Factor 3: Relative Strength vs Nifty ---
    if len(close) >= 10:
        stock_10d_return = (close.iloc[-1] / close.iloc[-10] - 1) * 100
        rs_diff = stock_10d_return - inp.nifty_10d_return

        if rs_diff >= 5:
            pts = 20
        elif rs_diff >= 3:
            pts = 15
        elif rs_diff >= 1:
            pts = 10
        elif rs_diff >= 0:
            pts = 5
        else:
            pts = 0
        score += pts
        breakdown['Rel Strength'] = (pts, f"{rs_diff:+.1f}% vs Nifty 10d")
    else:
        breakdown['Rel Strength'] = (0, "N/A")

    # --- Factor 4: Trend Alignment ---
    ema_10 = close.ewm(span=10, adjust=False).mean().iloc[-1]
    ema_20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema_50 = close.ewm(span=50, adjust=False).mean().iloc[-1]

    if current_close > ema_10 > ema_20 > ema_50:
        pts = 20
        tag = "Perfect stack (P>10>20>50)"
    elif current_close > ema_20 > ema_50:
        pts = 15
        tag = "Good (P>20>50)"
    elif current_close > ema_50:
        pts = 10
        tag = "Above 50 EMA"
    elif current_close > ema_20:
        pts = 5
        tag = "Above 20 EMA only"
    else:
        pts = 0
        tag = "Bearish alignment"

    score += pts
    breakdown['EMA Trend'] = (pts, tag)

    # --- Factor 5: Momentum / RSI ---
    rsi_series = compute_rsi(close, 14)
    rsi_val = float(rsi_series.iloc[-1])

    if 55 <= rsi_val <= 70:
        pts = 20
        tag = f"Sweet spot ({rsi_val:.0f})"
    elif 50 <= rsi_val < 55:
        pts = 15
        tag = f"Neutral-bull ({rsi_val:.0f})"
    elif 40 <= rsi_val < 50:
        pts = 10
        tag = f"Neutral ({rsi_val:.0f})"
    elif rsi_val > 70:
        pts = 5
        tag = f"Overbought ({rsi_val:.0f}) WARN"
    else:
        pts = 0
        tag = f"Weak ({rsi_val:.0f})"

    score += pts
    breakdown['RSI'] = (pts, tag)

    # --- Penalties ---
    dist_from_ema20_pct = (current_close - ema_20) / ema_20 * 100
    ext_thresholds = (8, 5, 3) if inp.universe == "small" else (12, 8, 5)

    if dist_from_ema20_pct > ext_thresholds[0]:
        score += -15
        penalties.append(f"Overextended {dist_from_ema20_pct:.1f}% above 20EMA (-15)")
    elif dist_from_ema20_pct > ext_thresholds[1]:
        score += -10
        penalties.append(f"Extended {dist_from_ema20_pct:.1f}% above 20EMA (-10)")
    elif dist_from_ema20_pct > ext_thresholds[2]:
        score += -5
        penalties.append(f"Slightly extended {dist_from_ema20_pct:.1f}% above 20EMA (-5)")

    if inp.universe == "small" and avg_vol_20 < 500000:
        score += -10
        penalties.append(f"Thin spread (avg vol {avg_vol_20/1e6:.1f}M < 500K) (-10)")

    if score >= 40 and vol_ratio < 1.0:
        score += -15
        penalties.append(f"LOW VOLUME ({vol_ratio:.1f}x) on breakout (-15)")

    # --- News Sentiment ---
    if inp.sentiment_7d != 0.0 or inp.has_reg_risk:
        if inp.sentiment_7d <= -0.5:
            penalties.append(f"HIGHLY NEGATIVE SENTIMENT ({inp.sentiment_7d:.2f}) - BLOCKED")
            score = 0
        else:
            news_pts = int(inp.sentiment_7d * 10)
            if news_pts != 0:
                breakdown['News'] = (news_pts, f"Sentiment {inp.sentiment_7d:.2f}")
                score += news_pts

    score += inp.total_env_modifier
    if inp.has_reg_risk:
        penalties.append("REGULATORY RISK (Capped at 60)")
        score = min(score, 60)

    score = max(0, min(100, score))

    return ScoreResult(
        symbol=inp.symbol,
        score=score,
        passed_filters=(score >= 50),
        current_close=round(float(current_close), 2),
        vol_ratio=round(float(vol_ratio), 1),
        rsi_val=round(rsi_val, 0),
        avg_traded_value_cr=round(float(avg_traded_value_cr), 1),
        factor_breakdown=breakdown,
        penalties=penalties,
    )
