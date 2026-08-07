"""Tests for pipeline pick tracking, outcome enrichment, and weekly reports."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from hermes.analytics.pick_tracker import (
    PICK_EVENING_LARGE,
    PICK_MORNING,
    persist_evening_picks,
    persist_morning_picks,
)
from hermes.analytics.weekly_pick_report import generate_weekly_pick_report, week_range
from hermes.data.analytics_mongo import InMemoryAnalyticsStore
from hermes.data.analytics_models import Recommendation, RecommendationOutcome
from hermes.pipelines.steps.outcome_enricher import (
    enrich_due_picks,
    enrich_recommendation,
    enrich_pick,
)


@pytest.fixture
def screener_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pd.DataFrame({
        "Stock": ["M&M", "GAIL"],
        "Sector": ["Auto", "Energy"],
        "Close": [3398.5, 181.44],
        "Score": [86, 85],
        "Vol_Ratio": [2.3, 4.4],
        "RSI": [67.0, 66.0],
    }).to_csv("screener_results.csv", index=False)
    (tmp_path / "market_regime.txt").write_text("NEUTRAL-BULL")
    return tmp_path


def test_persist_evening_picks(screener_files):
    plan = {
        "trading_date": "2026-08-04",
        "symbols": {"M&M": "2031", "GAIL": "4717"},
    }
    (screener_files / "trade_plan.json").write_text(json.dumps(plan))

    store = InMemoryAnalyticsStore()
    count = persist_evening_picks(store)

    assert count == 2
    picks = store.get_pipeline_picks()
    assert len(picks) == 2
    assert all(p.pick_source == PICK_EVENING_LARGE for p in picks)
    assert picks[0].entry_price > 0
    assert picks[0].target_price > picks[0].entry_price


def test_persist_morning_picks(screener_files):
    plan = {
        "trading_date": "2026-08-04",
        "gap_prediction_pct": 0.6,
        "rankings": [
            {
                "symbol": "M&M",
                "morning_score": 65.8,
                "screener_score": 86,
                "sentiment_7d": 0.185,
                "sector": "Auto",
                "vol_ratio": 2.3,
                "rsi": 67.0,
                "security_id": "2031",
                "in_evening_plan": True,
            },
        ],
    }
    (screener_files / "morning_trade_plan.json").write_text(json.dumps(plan))

    store = InMemoryAnalyticsStore()
    count = persist_morning_picks(store)

    assert count == 1
    picks = store.get_pipeline_picks(pick_source=PICK_MORNING)
    assert picks[0].symbol == "M&M"
    assert picks[0].confidence_score == 65.8


def test_pipeline_pick_upsert_preserves_id(screener_files):
    plan = {"trading_date": "2026-08-04", "symbols": {"M&M": "2031"}}
    (screener_files / "trade_plan.json").write_text(json.dumps(plan))

    store = InMemoryAnalyticsStore()
    persist_evening_picks(store)
    first_id = store.get_pipeline_picks()[0].recommendation_id

    persist_evening_picks(store)
    second_id = store.get_pipeline_picks()[0].recommendation_id

    assert first_id == second_id
    assert len(store.get_pipeline_picks()) == 1


def test_enrich_recommendation_buy():
    rec = Recommendation(
        symbol="M&M",
        action="BUY",
        entry_price=100.0,
        target_price=102.0,
        stop_loss=99.0,
    )
    outcome = enrich_recommendation(rec, day_open=100, day_high=103, day_low=98.5, day_close=101)
    assert outcome.target_hit is True
    assert outcome.final_pnl_pct == 1.0
    assert outcome.max_gain_pct == 3.0


@patch("hermes.pipelines.steps.outcome_enricher.fetch_day_ohlc")
def test_enrich_pick_saves_evaluation(mock_fetch):
    mock_fetch.return_value = {"open": 100, "high": 103, "low": 99, "close": 101}
    store = InMemoryAnalyticsStore()
    rec = Recommendation(
        recommendation_id="REC-TEST001",
        trading_date="2026-08-01",
        symbol="M&M",
        pick_source=PICK_EVENING_LARGE,
        strategy="PIPELINE",
        action="BUY",
        entry_price=100,
        target_price=102,
        stop_loss=99,
    )
    store.save_pipeline_pick(rec)

    assert enrich_pick(store, rec) is True
    assert len(store.get_evaluations()) == 1
    ev = store.get_evaluations()[0]
    assert ev["symbol"] == "M&M"
    assert ev["return_pct"] == 1.0


@patch("hermes.pipelines.steps.outcome_enricher.fetch_day_ohlc")
def test_enrich_due_picks_skips_evaluated(mock_fetch):
    mock_fetch.return_value = {"open": 100, "high": 102, "low": 99, "close": 101}
    store = InMemoryAnalyticsStore()
    rec = Recommendation(
        recommendation_id="REC-TEST002",
        trading_date="2026-08-01",
        symbol="GAIL",
        pick_source=PICK_EVENING_LARGE,
        strategy="PIPELINE",
        entry_price=100,
        target_price=102,
        stop_loss=99,
    )
    store.save_pipeline_pick(rec)
    store.save_evaluation({"recommendation_id": rec.recommendation_id, "trading_date": "2026-08-01"})

    count = enrich_due_picks(store, through_date=date(2026, 8, 1))
    assert count == 0


def test_week_range_monday_friday():
    # Saturday Aug 1 2026 -> last trading week Mon Jul 27 to Fri Jul 31
    mon, fri = week_range(date(2026, 8, 1))
    assert mon == date(2026, 7, 27)
    assert fri == date(2026, 7, 31)
    assert mon.weekday() == 0
    assert fri.weekday() == 4


def test_week_range_midweek():
    mon, fri = week_range(date(2026, 7, 30))
    assert mon == date(2026, 7, 27)
    assert fri == date(2026, 7, 31)


def test_week_range_friday_cron():
    mon, fri = week_range(date(2026, 8, 7))
    assert mon == date(2026, 8, 3)
    assert fri == date(2026, 8, 7)


def test_generate_weekly_pick_report_with_data():
    store = InMemoryAnalyticsStore()
    rec = Recommendation(
        recommendation_id="REC-W1",
        trading_date="2026-08-01",
        symbol="M&M",
        pick_source=PICK_EVENING_LARGE,
        strategy="PIPELINE",
        confidence_score=86,
        entry_price=100,
    )
    store.save_pipeline_pick(rec)
    store.save_evaluation({
        "recommendation_id": "REC-W1",
        "trading_date": "2026-08-01",
        "symbol": "M&M",
        "pick_source": PICK_EVENING_LARGE,
        "outcome_label": "SUCCESSFUL",
        "return_pct": 2.5,
        "outcome": {
            "recommendation_id": "REC-W1",
            "symbol": "M&M",
            "trading_date": "2026-08-01",
            "actual_entry_price": 100,
            "highest_price_reached": 103,
            "lowest_price_reached": 99,
            "closing_price": 102.5,
            "max_gain_pct": 3.0,
            "max_drawdown_pct": -1.0,
            "target_hit": True,
            "stop_loss_hit": False,
            "final_pnl_pct": 2.5,
        },
    })

    report = generate_weekly_pick_report(
        date(2026, 8, 1),
        date(2026, 8, 1),
        store=store,
    )
    assert "Weekly Pipeline Pick Report" in report
    assert "M&M" in report
    assert "86" in report
    assert "Win rate" in report


def test_generate_weekly_pick_report_upcoming_picks():
    store = InMemoryAnalyticsStore()
    rec = Recommendation(
        recommendation_id="REC-FUTURE",
        trading_date="2026-08-04",
        symbol="M&M",
        pick_source=PICK_EVENING_LARGE,
        strategy="PIPELINE",
    )
    store.save_pipeline_pick(rec)
    report = generate_weekly_pick_report(date(2026, 7, 28), date(2026, 8, 1), store=store)
    assert "upcoming session" in report.lower() or "2026-08-04" in report
    assert "pending until then" in report.lower() or "next trading day" in report.lower()


def test_generate_weekly_pick_report_no_mongo(monkeypatch):
    monkeypatch.setattr("hermes.analytics.weekly_pick_report.get_analytics_store", lambda: None)
    report = generate_weekly_pick_report()
    assert "MongoDB not configured" in report


def test_backfill_picks_from_runs(tmp_path, monkeypatch):
    from hermes import artifacts
    from hermes.analytics.pick_tracker import backfill_picks_from_runs

    monkeypatch.setenv("HERMES_VAR_DIR", str(tmp_path / "var"))
    run_dir = artifacts.run_dir(date(2026, 8, 4))
    run_dir.mkdir(parents=True)

    plan = {"trading_date": "2026-08-05", "symbols": {"M&M": "2031"}}
    (run_dir / "trade_plan.json").write_text(json.dumps(plan))
    pd.DataFrame({
        "Stock": ["M&M"],
        "Sector": ["Auto"],
        "Close": [3400.0],
        "Score": [86],
        "Vol_Ratio": [2.3],
        "RSI": [67.0],
    }).to_csv(run_dir / "screener_results.csv", index=False)

    store = InMemoryAnalyticsStore()
    count = backfill_picks_from_runs(store)
    assert count == 1
    picks = store.get_pipeline_picks()
    assert picks[0].symbol == "M&M"
    assert picks[0].trading_date == "2026-08-05"
