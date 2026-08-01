"""Unit tests for market snapshot job."""

from hermes.pipelines.steps.market_snapshot_job import MarketSnapshot, build_market_snapshot


class TestMarketSnapshot:
    def test_market_snapshot_structure(self):
        snapshot = MarketSnapshot(
            trading_date="2026-08-01",
            nifty50_close=24500.0,
            nifty50_change_pct=0.5,
            banknifty_close=52000.0,
            banknifty_change_pct=-0.2,
            india_vix=14.5,
            top_gainers=[{"symbol": "RELIANCE", "change_pct": 2.5}],
            top_losers=[{"symbol": "TCS", "change_pct": -1.8}],
            sector_performance={"IT": -0.8, "Banking": 0.5},
            advance_count=30,
            decline_count=20,
            market_breadth="BULLISH",
        )
        assert snapshot.trading_date == "2026-08-01"
        assert snapshot.market_breadth == "BULLISH"
        assert len(snapshot.top_gainers) == 1
        assert snapshot.sector_performance["IT"] == -0.8
