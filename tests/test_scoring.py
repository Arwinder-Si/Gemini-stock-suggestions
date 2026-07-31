import pandas as pd
import numpy as np
import pytest
from scoring import score_stock, ScoreInput, ScoreResult

def test_score_stock_basic():
    # Generate 100 days of mock stock price & volume data
    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=100)
    close = pd.Series(np.linspace(100, 150, 100), index=dates)
    high = close + 2.0
    low = close - 2.0
    volume = pd.Series([500000] * 99 + [1500000], index=dates)  # 3x volume surge on last day

    inp = ScoreInput(
        symbol="TEST",
        close=close,
        high=high,
        low=low,
        volume=volume,
        nifty_10d_return=1.0,
        total_env_modifier=5,
    )

    res: ScoreResult = score_stock(inp)
    assert res.symbol == "TEST"
    assert res.score > 50
    assert res.passed_filters is True
    assert res.vol_ratio >= 2.5
    assert "Volume" in res.factor_breakdown
