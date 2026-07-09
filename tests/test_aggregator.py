"""Unit tests for CandleAggregator — tick-to-candle conversion logic."""

from datetime import datetime

from market_feed import CandleAggregator


class TestSameMinuteTicks:
    """Ticks within the same minute should accumulate into a single candle."""

    def test_no_candle_returned_within_minute(self):
        agg = CandleAggregator(cumulative_volume=False)

        assert agg.process_tick("SYM", datetime(2023, 1, 1, 9, 15, 10), 100.0, 10) is None
        assert agg.process_tick("SYM", datetime(2023, 1, 1, 9, 15, 45), 105.0, 20) is None

    def test_ohlcv_state_correct(self):
        agg = CandleAggregator(cumulative_volume=False)

        agg.process_tick("SYM", datetime(2023, 1, 1, 9, 15, 10), 100.0, 10)
        agg.process_tick("SYM", datetime(2023, 1, 1, 9, 15, 30), 98.0, 5)
        agg.process_tick("SYM", datetime(2023, 1, 1, 9, 15, 45), 105.0, 20)

        state = agg.current_candles["SYM"]
        assert state["open"] == 100.0
        assert state["high"] == 105.0
        assert state["low"] == 98.0
        assert state["close"] == 105.0
        assert state["volume"] == 35  # 10 + 5 + 20


class TestMinuteBoundary:
    """When a tick crosses into a new minute, the previous candle finalizes."""

    def test_returns_finalized_candle(self):
        agg = CandleAggregator(cumulative_volume=False)

        agg.process_tick("SYM", datetime(2023, 1, 1, 9, 15, 10), 100.0, 10)
        agg.process_tick("SYM", datetime(2023, 1, 1, 9, 15, 45), 105.0, 20)

        candle = agg.process_tick("SYM", datetime(2023, 1, 1, 9, 16, 5), 102.0, 15)

        assert candle is not None
        assert candle.symbol == "SYM"
        assert candle.timestamp == "2023-01-01 09:15:00"
        assert candle.open == 100.0
        assert candle.high == 105.0
        assert candle.low == 100.0
        assert candle.close == 105.0
        assert candle.volume == 30

    def test_new_candle_state_started(self):
        agg = CandleAggregator(cumulative_volume=False)

        agg.process_tick("SYM", datetime(2023, 1, 1, 9, 15, 10), 100.0, 10)
        agg.process_tick("SYM", datetime(2023, 1, 1, 9, 16, 5), 102.0, 15)

        state = agg.current_candles["SYM"]
        assert state["timestamp"] == "2023-01-01 09:16:00"
        assert state["open"] == 102.0
        assert state["volume"] == 15


class TestMultiSymbol:
    """Ticks for different symbols should produce independent candles."""

    def test_interleaved_symbols(self):
        agg = CandleAggregator(cumulative_volume=False)

        agg.process_tick("A", datetime(2023, 1, 1, 9, 15, 10), 100.0, 10)
        agg.process_tick("B", datetime(2023, 1, 1, 9, 15, 20), 200.0, 50)
        agg.process_tick("A", datetime(2023, 1, 1, 9, 15, 30), 110.0, 5)

        # Cross minute boundary for A only
        candle_a = agg.process_tick("A", datetime(2023, 1, 1, 9, 16, 1), 108.0, 3)
        assert candle_a is not None
        assert candle_a.symbol == "A"
        assert candle_a.high == 110.0

        # B should still be accumulating
        assert "B" in agg.current_candles
        assert agg.current_candles["B"]["timestamp"] == "2023-01-01 09:15:00"


class TestCumulativeVolume:
    """When cumulative_volume=True, volume deltas are computed correctly."""

    def test_cumulative_volume_delta(self):
        agg = CandleAggregator(cumulative_volume=True)

        # First tick — delta is 0 (baseline)
        agg.process_tick("SYM", datetime(2023, 1, 1, 9, 15, 10), 100.0, 1000)
        assert agg.current_candles["SYM"]["volume"] == 0

        # Second tick — cumulative went from 1000 to 1500 → delta = 500
        agg.process_tick("SYM", datetime(2023, 1, 1, 9, 15, 30), 102.0, 1500)
        assert agg.current_candles["SYM"]["volume"] == 500
