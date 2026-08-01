"""Unit tests for ORBBreakoutStrategy — signal generation logic."""

from datetime import time as dt_time

import pytest

from hermes.domain.models import Candle
from hermes.domain.strategy import ORBBreakoutStrategy, ORBConfig

# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def orb_cfg() -> ORBConfig:
    """Standard test config: ORB 09:15–09:30, min vol 1000, 1:1 RR."""
    return ORBConfig(
        orb_start=dt_time(9, 15),
        orb_end=dt_time(9, 30),
        min_volume=1000,
        rr_ratio=1.0,
        exit_time=dt_time(15, 15),
    )


@pytest.fixture
def strategy(orb_cfg: ORBConfig) -> ORBBreakoutStrategy:
    return ORBBreakoutStrategy(orb_cfg)


SYM = "RELIANCE"


# ── ORB Window Tests ─────────────────────────────────────────────────

class TestORBWindow:
    def test_no_signal_during_orb_window(self, strategy: ORBBreakoutStrategy):
        c = Candle(SYM, "2023-10-10 09:15:00", 100, 105, 95, 102, 5000)
        assert strategy.on_candle(c) is None

    def test_orb_range_tracked(self, strategy: ORBBreakoutStrategy):
        strategy.on_candle(Candle(SYM, "2023-10-10 09:15:00", 100, 105, 95, 102, 500))
        strategy.on_candle(Candle(SYM, "2023-10-10 09:20:00", 102, 110, 98, 108, 500))
        strategy.on_candle(Candle(SYM, "2023-10-10 09:30:00", 108, 112, 100, 110, 500))

        state = strategy._state[SYM]
        assert state["orb_high"] == 112
        assert state["orb_low"] == 95


# ── Long Signal Tests ────────────────────────────────────────────────

class TestLongSignal:
    def test_long_breakout(self, strategy: ORBBreakoutStrategy):
        # Build ORB: high=105, low=98
        strategy.on_candle(Candle(SYM, "2023-10-10 09:15:00", 100, 103, 98, 102, 500))
        strategy.on_candle(Candle(SYM, "2023-10-10 09:30:00", 102, 105, 100, 104, 500))

        # Breakout candle: close 106 (+6% from open)
        sig = strategy.on_candle(Candle(SYM, "2023-10-10 09:35:00", 104, 107, 103, 106, 1500))

        assert sig is not None
        assert sig.direction == "LONG"
        assert sig.entry == 106
        assert sig.sl == 98
        assert sig.tp == 106 + (106 - 98)  # 114.0

    def test_no_re_entry_after_long(self, strategy: ORBBreakoutStrategy):
        strategy.on_candle(Candle(SYM, "2023-10-10 09:15:00", 100, 103, 98, 102, 500))
        strategy.on_candle(Candle(SYM, "2023-10-10 09:30:00", 102, 105, 100, 104, 500))
        strategy.on_candle(Candle(SYM, "2023-10-10 09:35:00", 104, 107, 103, 106, 1500))

        # Second breakout should be ignored
        sig = strategy.on_candle(Candle(SYM, "2023-10-10 09:40:00", 106, 109, 105, 108, 1500))
        assert sig is None


# ── Short Signal Tests ───────────────────────────────────────────────

class TestShortSignal:
    def test_short_breakout(self, strategy: ORBBreakoutStrategy):
        strategy.on_candle(Candle(SYM, "2023-10-10 09:15:00", 100, 105, 95, 102, 500))

        sig = strategy.on_candle(Candle(SYM, "2023-10-10 09:35:00", 102, 103, 90, 92, 1500))

        assert sig is not None
        assert sig.direction == "SHORT"
        assert sig.entry == 92
        assert sig.sl == 105
        assert sig.tp == 92 - (105 - 92)  # 79.0


# ── Rejection Tests ──────────────────────────────────────────────────

class TestRejections:
    def test_low_volume_rejected(self, strategy: ORBBreakoutStrategy):
        strategy.on_candle(Candle(SYM, "2023-10-10 09:15:00", 100, 105, 95, 102, 500))

        sig = strategy.on_candle(Candle(SYM, "2023-10-10 09:35:00", 102, 115, 101, 112, 500))
        assert sig is None

    def test_no_signal_after_exit_time(self, strategy: ORBBreakoutStrategy):
        strategy.on_candle(Candle(SYM, "2023-10-10 09:15:00", 100, 105, 95, 102, 500))

        sig = strategy.on_candle(Candle(SYM, "2023-10-10 15:20:00", 102, 115, 101, 112, 5000))
        assert sig is None

    def test_close_inside_range_no_signal(self, strategy: ORBBreakoutStrategy):
        strategy.on_candle(Candle(SYM, "2023-10-10 09:15:00", 100, 105, 95, 102, 500))

        sig = strategy.on_candle(Candle(SYM, "2023-10-10 09:35:00", 100, 104, 96, 101, 5000))
        assert sig is None


# ── Multi-Symbol / Multi-Day ─────────────────────────────────────────

class TestMultiSymbolMultiDay:
    def test_per_symbol_state_is_independent(self, strategy: ORBBreakoutStrategy):
        # Build ORB for SYM_A
        strategy.on_candle(Candle("A", "2023-10-10 09:15:00", 100, 103, 98, 102, 500))
        # Build ORB for SYM_B
        strategy.on_candle(Candle("B", "2023-10-10 09:15:00", 200, 205, 195, 202, 500))

        # Breakout A — should not affect B's state
        sig_a = strategy.on_candle(Candle("A", "2023-10-10 09:35:00", 102, 107, 101, 105, 1500))
        assert sig_a is not None
        assert sig_a.symbol == "A"
        assert strategy._state["B"]["signal_fired"] is False

    def test_new_day_resets_per_symbol(self, strategy: ORBBreakoutStrategy):
        # Day 1 signal
        strategy.on_candle(Candle(SYM, "2023-10-10 09:15:00", 100, 103, 98, 102, 500))
        sig1 = strategy.on_candle(Candle(SYM, "2023-10-10 09:35:00", 102, 107, 101, 105, 1500))
        assert sig1 is not None

        # Day 2 — should be able to fire again
        strategy.on_candle(Candle(SYM, "2023-10-11 09:15:00", 200, 205, 195, 202, 500))
        sig2 = strategy.on_candle(Candle(SYM, "2023-10-11 09:35:00", 202, 209, 201, 207, 1500))
        assert sig2 is not None
        assert sig2.entry == 207
