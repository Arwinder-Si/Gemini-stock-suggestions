import pandas as pd
import numpy as np
import pytest
from datetime import datetime, time as dt_time
from backtest import ORBBacktester
from strategy import ORBConfig
from costs import CostModel

def test_orb_backtester_multi_symbol():
    orb_cfg = ORBConfig(
        orb_start=dt_time(9, 15),
        orb_end=dt_time(9, 30),
        min_volume=1000,
        rr_ratio=1.0,
        exit_time=dt_time(15, 15),
    )
    cost_model = CostModel(slippage_bps=0)
    bt = ORBBacktester(cfg=orb_cfg, cost_model=cost_model)

    # Create mock 1-min candles for SYM1
    dates = pd.date_range("2026-07-01 09:15:00", periods=30, freq="1min")
    df_sym1 = pd.DataFrame({
        "timestamp": dates,
        "open": [100.0] * 30,
        "high": [105.0] * 15 + [112.0] * 15,
        "low": [98.0] * 30,
        "close": [102.0] * 15 + [110.0] * 15,
        "volume": [500] * 15 + [2000] * 15,
    })

    metrics = bt.run({"SYM1": df_sym1})
    assert "total_trades" in metrics
