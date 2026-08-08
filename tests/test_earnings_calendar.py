"""Tests for earnings calendar parsing and morning refiner integration."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from hermes.domain.earnings_calendar import (
    bucket_symbols,
    build_calendar_document,
    parse_result_date_from_headline,
    refresh_buckets,
)
from hermes.domain.morning_score import compute_morning_score
from hermes.pipelines.steps import morning_refiner


def test_parse_result_date_from_headline_august():
    ref = date(2026, 8, 7)
    headline = "Company to announce Q1 FY26 results on August 8, 2026"
    parsed = parse_result_date_from_headline(headline, ref)
    assert parsed == date(2026, 8, 8)


def test_parse_result_date_dd_mon_yyyy():
    ref = date(2026, 8, 7)
    parsed = parse_result_date_from_headline("Board meeting on 08-Aug-2026 for quarterly results", ref)
    assert parsed == date(2026, 8, 8)


def test_bucket_symbols_today_and_tomorrow():
    entries = {
        "AAA": {"result_date": "2026-08-08", "source": "news"},
        "BBB": {"result_date": "2026-08-09", "source": "yfinance"},
    }
    today, tomorrow = bucket_symbols(entries, date(2026, 8, 8))
    assert today == ["AAA"]
    assert tomorrow == ["BBB"]


def test_build_calendar_document_merges_news(monkeypatch):
    ref = date(2026, 8, 7)

    def fake_yf(symbol: str, as_of: date):
        return None

    monkeypatch.setattr(
        "hermes.domain.earnings_calendar.fetch_yfinance_earnings_date",
        fake_yf,
    )

    doc = build_calendar_document(
        ["NYKAA"],
        ref,
        news_rows=[{"symbol": "NYKAA", "top_headline": "NYKAA results scheduled for August 8, 2026"}],
        fetch_delay_sec=0,
    )
    assert "NYKAA" in doc["entries"]
    assert doc["entries"]["NYKAA"]["source"] == "news"
    assert "NYKAA" in doc["result_tomorrow"]


def test_refresh_buckets_updates_as_of():
    doc = {
        "entries": {"X": {"result_date": "2026-08-10", "source": "news"}},
        "result_today": [],
        "result_tomorrow": [],
        "as_of_date": "2026-08-07",
    }
    refreshed = refresh_buckets(doc, date(2026, 8, 9))
    assert refreshed["as_of_date"] == "2026-08-09"
    assert refreshed["result_tomorrow"] == ["X"]


def test_compute_morning_score_earnings_boost():
    base = compute_morning_score(80, 0.0, 0.0)
    boosted = compute_morning_score(80, 0.0, 0.0, earnings_result_today=True)
    assert base is not None and boosted is not None
    assert boosted == base + 8.0


def test_refine_morning_plan_earnings_boost(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    pd.DataFrame([
        {"Stock": "M&M", "Sector": "Auto", "Close": 3400, "Score": 86,
         "Vol_Ratio": 2.3, "RSI": 67, "Liq_Cr": 800, "Dist_EMA20": 6.2},
    ]).to_csv("screener_results.csv", index=False)

    pd.DataFrame([
        {"symbol": "M&M", "sentiment_7d": 0.0, "has_neg_reg_news_7d": False},
    ]).to_csv("news_features.csv", index=False)

    json.dump({"M&M": "2031"}, open("nse_eq_mapping.json", "w"))
    json.dump({"trading_date": "2026-08-03", "symbols": {"M&M": "2031"}}, open("trade_plan.json", "w"))
    Path("market_regime.txt").write_text("NEUTRAL")

    json.dump(
        {
            "as_of_date": "2026-08-03",
            "entries": {"M&M": {"result_date": "2026-08-03", "source": "news"}},
            "result_today": ["M&M"],
            "result_tomorrow": [],
        },
        open("earnings_calendar.json", "w"),
    )

    monkeypatch.setattr(
        "hermes.pipelines.steps.morning_refiner.market_db.get_latest_gap_prediction",
        lambda: {"prediction_pct": 0.8, "bias": "Strong Bullish Open"},
    )
    monkeypatch.setattr("hermes.pipelines.steps.morning_refiner.trading_date_ist", lambda: date(2026, 8, 3))

    plan = morning_refiner.refine_morning_plan()
    assert plan["rankings"][0]["earnings_result_today"] is True
    assert plan["earnings_result_today"] == ["M&M"]
