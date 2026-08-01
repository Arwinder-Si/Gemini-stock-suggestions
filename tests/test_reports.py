"""Unit tests for daily comparison report and analytics report modules."""

from unittest.mock import MagicMock, patch

from hermes.data.analytics_models import PaperTrade, FailureAnalysis
from hermes.analytics.daily_report import build_daily_comparison, format_daily_report
from hermes.analytics.analytics_report import (
    generate_strategy_report,
    generate_sector_report,
    generate_failure_tag_report,
    generate_improvement_suggestions,
    generate_full_analytics_report,
    print_stats_summary,
)


class TestDailyReport:
    def test_build_daily_comparison_empty(self):
        rep = build_daily_comparison([], trading_date_str="2026-08-01")
        assert rep.trading_date == "2026-08-01"
        assert rep.paper_trades_count == 0
        assert "No paper trades executed today." in rep.notes[0]

    def test_build_daily_comparison_with_trades(self):
        trades = [
            PaperTrade(trade_id="T1", trading_date="2026-08-01", net_pnl=500.0),
            PaperTrade(trade_id="T2", trading_date="2026-08-01", net_pnl=-200.0),
        ]
        rep = build_daily_comparison(trades, trading_date_str="2026-08-01")
        assert rep.paper_trades_count == 2
        assert rep.paper_net_pnl == 300.0
        assert rep.paper_win_rate == 50.0

        formatted = format_daily_report(rep)
        assert "Daily Report" in formatted
        assert "2026-08-01" in formatted
        assert "**Paper Trades:** 2" in formatted


class TestAnalyticsReport:
    def test_generate_strategy_report(self):
        trades = [
            PaperTrade(strategy="ORB_LARGE", net_pnl=500.0),
            PaperTrade(strategy="ORB_LARGE", net_pnl=-100.0),
            PaperTrade(strategy="ORB_SMALL", net_pnl=200.0),
        ]
        rpt = generate_strategy_report(trades)
        assert "ORB_LARGE" in rpt
        assert "ORB_SMALL" in rpt

    def test_generate_sector_report(self):
        trades = [
            PaperTrade(symbol="RELIANCE", net_pnl=500.0),
            PaperTrade(symbol="TCS", net_pnl=-100.0),
        ]
        rpt = generate_sector_report(trades)
        assert "Oil & Gas" in rpt or "IT" in rpt

    def test_generate_failure_tag_report(self):
        analyses = [
            FailureAnalysis(root_cause_tags=["POOR_SL_PLACEMENT", "HIGH_VOLATILITY"]),
            FailureAnalysis(root_cause_tags=["POOR_SL_PLACEMENT"]),
        ]
        rpt = generate_failure_tag_report(analyses)
        assert "POOR_SL_PLACEMENT" in rpt
        assert "HIGH_VOLATILITY" in rpt

    def test_generate_improvement_suggestions(self):
        trades = [
            PaperTrade(net_pnl=-600.0, exit_reason="SL Hit"),
            PaperTrade(net_pnl=-700.0, exit_reason="Time Exit"),
        ]
        analyses = [
            FailureAnalysis(root_cause_tags=["POOR_SL_PLACEMENT"]),
            FailureAnalysis(root_cause_tags=["POOR_SL_PLACEMENT"]),
            FailureAnalysis(root_cause_tags=["POOR_SL_PLACEMENT"]),
        ]
        sug = generate_improvement_suggestions(trades, analyses)
        assert "Improvement Suggestions" in sug

    def test_generate_full_analytics_report(self):
        trades = [PaperTrade(strategy="ORB_LARGE", symbol="RELIANCE", net_pnl=500.0)]
        full_rpt = generate_full_analytics_report(trades)
        assert "Strategy Performance" in full_rpt
        assert "Sector Performance" in full_rpt


class TestPrintStatsSummary:
    @patch("hermes.config.get_config")
    def test_no_mongodb_uri(self, mock_cfg):
        mock_cfg.return_value = MagicMock(mongodb_uri="")
        msg = print_stats_summary()
        assert "MongoDB not configured" in msg

    @patch("hermes.data.analytics_mongo.MongoAnalyticsStore")
    @patch("hermes.config.get_config")
    def test_reads_from_mongo(self, mock_cfg, mock_store_cls):
        mock_cfg.return_value = MagicMock(
            mongodb_uri="mongodb+srv://x",
            mongodb_tls_insecure=False,
        )
        store = mock_store_cls.return_value
        store.get_paper_trades.side_effect = [
            [PaperTrade(trade_id="T1", trading_date="2026-08-01", net_pnl=100.0)],
            [
                PaperTrade(trade_id="T1", trading_date="2026-08-01", net_pnl=100.0),
                PaperTrade(trade_id="T2", trading_date="2026-07-31", net_pnl=-50.0),
            ],
        ]
        msg = print_stats_summary()
        assert "Analytics Summary" in msg
        assert "Win Rate" in msg
        mock_store_cls.assert_called_once_with(
            "mongodb+srv://x",
            tls_insecure=False,
        )
