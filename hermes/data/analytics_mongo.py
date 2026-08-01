"""
MongoDB Atlas implementation of AnalyticsStore Protocol.
"""

from dataclasses import asdict
import logging
from typing import Any
from hermes.data.analytics_store import AnalyticsStore
from hermes.data.analytics_models import (
    Recommendation,
    PaperTrade,
    TradeJournalEntry,
    PortfolioSnapshot,
    FailureAnalysis,
)

logger = logging.getLogger(__name__)


def create_mongo_client(
    mongo_uri: str,
    *,
    tls_insecure: bool = False,
    server_selection_timeout_ms: int = 10000,
):
    """
    Build a pymongo client with explicit CA bundle (certifi).

    Corporate VMs sometimes fail Atlas TLS with the system CA store alone;
    certifi fixes most cases. MONGODB_TLS_INSECURE is a last resort behind
    SSL-inspecting proxies (dev/debug only).
    """
    import certifi
    import pymongo

    kwargs: dict = {"serverSelectionTimeoutMS": server_selection_timeout_ms}
    if mongo_uri.startswith("mongodb+srv://") or "tls=true" in mongo_uri.lower():
        kwargs["tlsCAFile"] = certifi.where()
    if tls_insecure:
        logger.warning("MONGODB_TLS_INSECURE enabled — TLS certificate verification disabled")
        kwargs["tlsAllowInvalidCertificates"] = True
    return pymongo.MongoClient(mongo_uri, **kwargs)


class MongoAnalyticsStore(AnalyticsStore):
    """MongoDB Atlas analytics store client with collection indexing."""

    def __init__(
        self,
        mongo_uri: str,
        db_name: str = "hermes_analytics",
        *,
        tls_insecure: bool = False,
    ):
        self.client = create_mongo_client(mongo_uri, tls_insecure=tls_insecure)
        self.db = self.client[db_name]
        self._create_indexes()

    def _create_indexes(self) -> None:
        try:
            self.db.recommendations.create_index([("trading_date", 1), ("symbol", 1)])
            self.db.paper_trades.create_index([("trade_id", 1)], unique=True)
            self.db.paper_trades.create_index([("trading_date", 1)])
            self.db.trade_journal.create_index([("journal_id", 1)], unique=True)
            self.db.portfolio_snapshots.create_index([("trading_date", 1)])
            self.db.failure_analyses.create_index([("trade_id", 1)])
            self.db.failure_analyses.create_index([("trading_date", 1)])
            self.db.market_snapshots.create_index([("trading_date", 1)], unique=True)
            self.db.evaluations.create_index([("recommendation_id", 1)])
            self.db.evaluations.create_index([("trading_date", 1)])
            logger.info("MongoDB analytics indexes initialized.")
        except Exception as e:
            logger.warning(f"Could not create Mongo indexes: {e}")

    def save_recommendation(self, rec: Recommendation) -> str:
        doc = asdict(rec)
        self.db.recommendations.insert_one(doc)
        return rec.recommendation_id

    def save_paper_trade(self, trade: PaperTrade) -> None:
        doc = asdict(trade)
        self.db.paper_trades.update_one({"trade_id": trade.trade_id}, {"$set": doc}, upsert=True)

    def save_journal_entry(self, entry: TradeJournalEntry) -> None:
        doc = asdict(entry)
        self.db.trade_journal.update_one({"journal_id": entry.journal_id}, {"$set": doc}, upsert=True)

    def save_portfolio_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        doc = asdict(snapshot)
        self.db.portfolio_snapshots.insert_one(doc)

    def save_failure_analysis(self, analysis: FailureAnalysis) -> None:
        doc = asdict(analysis)
        self.db.failure_analyses.insert_one(doc)

    def save_market_snapshot(self, snapshot: dict) -> None:
        if hasattr(snapshot, "__dict__"):
            from dataclasses import asdict as _asdict
            snapshot = _asdict(snapshot)
        self.db.market_snapshots.update_one(
            {"trading_date": snapshot.get("trading_date")},
            {"$set": snapshot},
            upsert=True,
        )

    def save_evaluation(self, evaluation: dict) -> None:
        if hasattr(evaluation, "__dict__"):
            from dataclasses import asdict as _asdict
            evaluation = _asdict(evaluation)
        self.db.evaluations.insert_one(evaluation)

    def get_recommendations(self, trading_date: str | None = None) -> list[Recommendation]:
        query = {"trading_date": trading_date} if trading_date else {}
        cursor = self.db.recommendations.find(query)
        results = []
        for doc in cursor:
            doc.pop("_id", None)
            results.append(Recommendation(**doc))
        return results

    def get_journal_entries(self, trading_date: str | None = None) -> list[TradeJournalEntry]:
        query = {"trading_date": trading_date} if trading_date else {}
        cursor = self.db.trade_journal.find(query)
        results = []
        for doc in cursor:
            doc.pop("_id", None)
            results.append(TradeJournalEntry(**doc))
        return results

    def get_paper_trades(self, trading_date: str | None = None) -> list[PaperTrade]:
        query = {"trading_date": trading_date} if trading_date else {}
        cursor = self.db.paper_trades.find(query)
        results = []
        for doc in cursor:
            doc.pop("_id", None)
            results.append(PaperTrade(**doc))
        return results

    def get_failure_analyses(self, trading_date: str | None = None) -> list[FailureAnalysis]:
        query = {"trading_date": trading_date} if trading_date else {}
        cursor = self.db.failure_analyses.find(query)
        results = []
        for doc in cursor:
            doc.pop("_id", None)
            results.append(FailureAnalysis(**doc))
        return results

    def get_portfolio_snapshots(self, trading_date: str | None = None) -> list[PortfolioSnapshot]:
        query = {"trading_date": trading_date} if trading_date else {}
        cursor = self.db.portfolio_snapshots.find(query)
        results = []
        for doc in cursor:
            doc.pop("_id", None)
            results.append(PortfolioSnapshot(**doc))
        return results


class InMemoryAnalyticsStore(AnalyticsStore):
    """In-memory analytics store for fast testing and CI."""

    def __init__(self):
        self.recommendations: list[Recommendation] = []
        self.paper_trades: list[PaperTrade] = []
        self.journal_entries: list[TradeJournalEntry] = []
        self.portfolio_snapshots: list[PortfolioSnapshot] = []
        self.failure_analyses: list[FailureAnalysis] = []
        self.market_snapshots: list[dict] = []
        self.evaluations: list[dict] = []

    def save_recommendation(self, rec: Recommendation) -> str:
        self.recommendations.append(rec)
        return rec.recommendation_id

    def save_paper_trade(self, trade: PaperTrade) -> None:
        self.paper_trades.append(trade)

    def save_journal_entry(self, entry: TradeJournalEntry) -> None:
        self.journal_entries.append(entry)

    def save_portfolio_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        self.portfolio_snapshots.append(snapshot)

    def save_failure_analysis(self, analysis: FailureAnalysis) -> None:
        self.failure_analyses.append(analysis)

    def save_market_snapshot(self, snapshot: dict) -> None:
        if hasattr(snapshot, "__dict__"):
            from dataclasses import asdict
            snapshot = asdict(snapshot)
        self.market_snapshots.append(snapshot)

    def save_evaluation(self, evaluation: dict) -> None:
        if hasattr(evaluation, "__dict__"):
            from dataclasses import asdict
            evaluation = asdict(evaluation)
        self.evaluations.append(evaluation)

    def get_recommendations(self, trading_date: str | None = None) -> list[Recommendation]:
        if trading_date:
            return [r for r in self.recommendations if r.trading_date == trading_date]
        return list(self.recommendations)

    def get_journal_entries(self, trading_date: str | None = None) -> list[TradeJournalEntry]:
        if trading_date:
            return [j for j in self.journal_entries if j.trading_date == trading_date]
        return list(self.journal_entries)

    def get_paper_trades(self, trading_date: str | None = None) -> list[PaperTrade]:
        if trading_date:
            return [t for t in self.paper_trades if t.trading_date == trading_date]
        return list(self.paper_trades)

    def get_failure_analyses(self, trading_date: str | None = None) -> list[FailureAnalysis]:
        if trading_date:
            return [a for a in self.failure_analyses if a.trading_date == trading_date]
        return list(self.failure_analyses)

    def get_portfolio_snapshots(self, trading_date: str | None = None) -> list[PortfolioSnapshot]:
        if trading_date:
            return [s for s in self.portfolio_snapshots if s.trading_date == trading_date]
        return list(self.portfolio_snapshots)
