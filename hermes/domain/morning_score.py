"""
Morning refinement scoring — combines evening screener output with overnight
news sentiment and global gap bias into a single morning_score.
"""

from __future__ import annotations


def compute_morning_score(
    screener_score: float,
    sentiment_7d: float,
    gap_prediction_pct: float,
    *,
    has_reg_risk: bool = False,
    market_regime: str = "UNKNOWN",
) -> float | None:
    """
    Return a 0–100 morning score, or None if the stock should be excluded.

    Weights (approximate):
      - 60% evening technical screener score
      - 25% news sentiment adjustment (±10 pts)
      - 15% global gap alignment (±10 pts)
      - small regime penalty in bearish conditions
    """
    if has_reg_risk:
        return None
    if sentiment_7d < -0.20:
        return None

    news_pts = max(-10.0, min(10.0, sentiment_7d * 50.0))

    if gap_prediction_pct >= 0.5:
        global_pts = 10.0
    elif gap_prediction_pct >= 0.1:
        global_pts = 5.0
    elif gap_prediction_pct > -0.1:
        global_pts = 0.0
    elif gap_prediction_pct > -0.5:
        global_pts = -5.0
    else:
        global_pts = -10.0

    regime_adj = -5.0 if "BEAR" in market_regime.upper() else 0.0

    raw = screener_score * 0.60 + news_pts + global_pts + regime_adj
    return round(max(0.0, min(100.0, raw)), 1)
