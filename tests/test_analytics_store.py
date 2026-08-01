import pytest
from hermes.data.analytics_mongo import InMemoryAnalyticsStore
from hermes.data.analytics_models import Recommendation, TradeJournalEntry

def test_in_memory_analytics_store():
    store = InMemoryAnalyticsStore()

    rec = Recommendation(
        trading_date="2026-07-31",
        symbol="RELIANCE",
        action="BUY",
        entry_price=2500.0,
    )
    rec_id = store.save_recommendation(rec)
    assert rec_id.startswith("REC-")
    assert len(store.get_recommendations("2026-07-31")) == 1

    entry = TradeJournalEntry(
        trading_date="2026-07-31",
        symbol="RELIANCE",
        net_pnl=500.0,
        is_win=True,
    )
    store.save_journal_entry(entry)
    assert len(store.get_journal_entries("2026-07-31")) == 1
