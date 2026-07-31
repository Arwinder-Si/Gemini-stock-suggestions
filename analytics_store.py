"""
Analytics Store Protocol interface.
Defines required methods for persisting recommendations, paper trades, journal entries,
portfolio snapshots, failure analyses, market snapshots, and evaluations.
"""

from typing import Protocol, runtime_checkable
from analytics_models import (
    Recommendation,
    PaperTrade,
    TradeJournalEntry,
    PortfolioSnapshot,
    FailureAnalysis,
)


@runtime_checkable
class AnalyticsStore(Protocol):

    def save_recommendation(self, rec: Recommendation) -> str:
        """Persist recommendation doc. Returns recommendation_id."""
        ...

    def save_paper_trade(self, trade: PaperTrade) -> None:
        """Persist executed paper trade doc."""
        ...

    def save_journal_entry(self, entry: TradeJournalEntry) -> None:
        """Persist completed trade journal doc."""
        ...

    def save_portfolio_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        """Persist EOD / intraday portfolio snapshot."""
        ...

    def save_failure_analysis(self, analysis: FailureAnalysis) -> None:
        """Persist root cause failure analysis record."""
        ...

    def save_market_snapshot(self, snapshot: dict) -> None:
        """Persist daily market benchmark snapshot."""
        ...

    def save_evaluation(self, evaluation: dict) -> None:
        """Persist trade evaluation record."""
        ...

    def get_recommendations(self, trading_date: str | None = None) -> list[Recommendation]:
        """Fetch recommendations matching filters."""
        ...

    def get_journal_entries(self, trading_date: str | None = None) -> list[TradeJournalEntry]:
        """Fetch journal entries matching filters."""
        ...

    def get_paper_trades(self, trading_date: str | None = None) -> list[PaperTrade]:
        """Fetch paper trades matching filters."""
        ...

    def get_failure_analyses(self, trading_date: str | None = None) -> list[FailureAnalysis]:
        """Fetch failure analyses matching filters."""
        ...

    def get_portfolio_snapshots(self, trading_date: str | None = None) -> list[PortfolioSnapshot]:
        """Fetch portfolio snapshots matching filters."""
        ...
