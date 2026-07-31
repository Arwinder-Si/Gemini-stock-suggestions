import tempfile
from pathlib import Path
from datetime import date
import pandas as pd
import pytest
from data_cache import CandleCache

def test_candle_cache_write_read_coverage():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = CandleCache(base_dir=tmpdir)

        # Create sample 1-min candles DataFrame
        df1 = pd.DataFrame([
            {"timestamp": "2026-07-01 09:15:00", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
            {"timestamp": "2026-07-01 09:16:00", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1500},
        ])

        df2 = pd.DataFrame([
            {"timestamp": "2026-07-01 09:16:00", "open": 101, "high": 103, "low": 100, "close": 102.5, "volume": 1600}, # update
            {"timestamp": "2026-07-02 09:15:00", "open": 102, "high": 104, "low": 101, "close": 103, "volume": 1200},
        ])

        cache.write("11536", df1)
        cache.write("11536", df2)

        # Read back
        res = cache.read("11536", start=date(2026, 7, 1), end=date(2026, 7, 2))
        assert len(res) == 3
        # Verify deduplication kept the latest value for 09:16:00
        row_0916 = res[res["timestamp"] == "2026-07-01 09:16:00"].iloc[0]
        assert row_0916["close"] == 102.5

        # Check coverage
        cov = cache.coverage("11536")
        assert len(cov) == 1
        assert cov[0] == (date(2026, 7, 1), date(2026, 7, 2))
