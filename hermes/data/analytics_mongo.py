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
        """Ensure indexes exist; use explicit names to avoid Atlas conflicts with legacy indexes."""
        index_specs: list[tuple[str, list, dict]] = [
            ("recommendations", [("trading_date", 1), ("symbol", 1)], {"name": "idx_rec_date_symbol"}),
            (
                "recommendations",
                [("trading_date", 1), ("symbol", 1), ("pick_source", 1)],
                {
                    "name": "idx_rec_pipeline_pick_unique",
                    "unique": True,
                    "partialFilterExpression": {"pick_source": {"$gt": ""}},
                },
            ),
            ("paper_trades", [("trade_id", 1)], {"name": "idx_paper_trades_trade_id", "unique": True}),
            ("paper_trades", [("trading_date", 1)], {"name": "idx_paper_trades_date"}),
            ("trade_journal", [("journal_id", 1)], {"name": "idx_journal_id", "unique": True}),
            ("portfolio_snapshots", [("trading_date", 1)], {"name": "idx_portfolio_date"}),
            ("failure_analyses", [("trade_id", 1)], {"name": "idx_failure_trade_id"}),
            ("failure_analyses", [("trading_date", 1)], {"name": "idx_failure_date"}),
            ("market_snapshots", [("trading_date", 1)], {"name": "idx_market_snap_date", "unique": True}),
            (
                "evaluations",
                [("recommendation_id", 1)],
                {"name": "idx_eval_recommendation_id_unique", "unique": True},
            ),
            ("evaluations", [("trading_date", 1)], {"name": "idx_eval_date"}),
            ("evaluations", [("pick_source", 1)], {"name": "idx_eval_pick_source"}),
        ]
        created = 0
        for coll_name, keys, kwargs in index_specs:
            try:
                self.db[coll_name].create_index(keys, **kwargs)
                created += 1
            except Exception as e:
                code = getattr(e, "code", None)
                if code in (85, 86):
                    logger.debug("Index %s on %s already exists: %s", kwargs.get("name"), coll_name, e)
                else:
                    logger.warning("Could not create index %s on %s: %s", kwargs.get("name"), coll_name, e)
        logger.info("MongoDB analytics indexes checked (%d specs).", len(index_specs))

    def save_recommendation(self, rec: Recommendation) -> str:
        doc = asdict(rec)
        self.db.recommendations.insert_one(doc)
        return rec.recommendation_id

    def save_pipeline_pick(self, rec: Recommendation) -> str:
        """Upsert a screener pipeline pick (evening/morning), keyed by date+symbol+source."""
        if not rec.pick_source:
            raise ValueError("pick_source is required for pipeline picks")
        filt = {
            "trading_date": rec.trading_date,
            "symbol": rec.symbol,
            "pick_source": rec.pick_source,
        }
        existing = self.db.recommendations.find_one(filt)
        doc = asdict(rec)
        if existing and existing.get("recommendation_id"):
            doc["recommendation_id"] = existing["recommendation_id"]
            rec.recommendation_id = existing["recommendation_id"]
        self.db.recommendations.update_one(filt, {"$set": doc}, upsert=True)
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
        rec_id = evaluation.get("recommendation_id")
        if rec_id:
            self.db.evaluations.update_one(
                {"recommendation_id": rec_id},
                {"$set": evaluation},
                upsert=True,
            )
        else:
            self.db.evaluations.insert_one(evaluation)

    def get_pipeline_picks(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        pick_source: str | None = None,
    ) -> list[Recommendation]:
        query: dict[str, Any] = {"pick_source": {"$gt": ""}}
        if pick_source:
            query["pick_source"] = pick_source
        if start_date and end_date:
            query["trading_date"] = {"$gte": start_date, "$lte": end_date}
        elif start_date:
            query["trading_date"] = {"$gte": start_date}
        elif end_date:
            query["trading_date"] = {"$lte": end_date}
        cursor = self.db.recommendations.find(query).sort("trading_date", 1)
        results = []
        for doc in cursor:
            doc.pop("_id", None)
            results.append(Recommendation(**doc))
        return results

    def get_evaluations(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        pick_source: str | None = None,
    ) -> list[dict]:
        query: dict[str, Any] = {}
        if pick_source:
            query["pick_source"] = pick_source
        if start_date and end_date:
            query["trading_date"] = {"$gte": start_date, "$lte": end_date}
        elif start_date:
            query["trading_date"] = {"$gte": start_date}
        elif end_date:
            query["trading_date"] = {"$lte": end_date}
        cursor = self.db.evaluations.find(query).sort("trading_date", 1)
        results = []
        for doc in cursor:
            doc.pop("_id", None)
            results.append(doc)
        return results

    def get_evaluated_recommendation_ids(self) -> set[str]:
        return {doc["recommendation_id"] for doc in self.db.evaluations.find({}, {"recommendation_id": 1})}

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

    def save_pipeline_pick(self, rec: Recommendation) -> str:
        if not rec.pick_source:
            raise ValueError("pick_source is required for pipeline picks")
        key = (rec.trading_date, rec.symbol, rec.pick_source)
        for i, existing in enumerate(self.recommendations):
            if (
                existing.trading_date == rec.trading_date
                and existing.symbol == rec.symbol
                and existing.pick_source == rec.pick_source
            ):
                rec.recommendation_id = existing.recommendation_id
                self.recommendations[i] = rec
                return rec.recommendation_id
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
        rec_id = evaluation.get("recommendation_id")
        for i, existing in enumerate(self.evaluations):
            if existing.get("recommendation_id") == rec_id:
                self.evaluations[i] = evaluation
                return
        self.evaluations.append(evaluation)

    def get_pipeline_picks(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        pick_source: str | None = None,
    ) -> list[Recommendation]:
        results = [r for r in self.recommendations if r.pick_source]
        if pick_source:
            results = [r for r in results if r.pick_source == pick_source]
        if start_date:
            results = [r for r in results if r.trading_date >= start_date]
        if end_date:
            results = [r for r in results if r.trading_date <= end_date]
        return sorted(results, key=lambda r: r.trading_date)

    def get_evaluations(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        pick_source: str | None = None,
    ) -> list[dict]:
        results = list(self.evaluations)
        if pick_source:
            results = [e for e in results if e.get("pick_source") == pick_source]
        if start_date:
            results = [e for e in results if e.get("trading_date", "") >= start_date]
        if end_date:
            results = [e for e in results if e.get("trading_date", "") <= end_date]
        return sorted(results, key=lambda e: e.get("trading_date", ""))

    def get_evaluated_recommendation_ids(self) -> set[str]:
        return {e["recommendation_id"] for e in self.evaluations if e.get("recommendation_id")}

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
