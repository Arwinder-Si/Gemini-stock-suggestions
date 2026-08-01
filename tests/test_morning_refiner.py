"""Tests for morning refiner and morning score logic."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from hermes.domain.morning_score import compute_morning_score
from hermes.pipelines.steps import morning_refiner


def test_compute_morning_score_excludes_reg_risk():
    assert compute_morning_score(85, 0.2, 0.6, has_reg_risk=True) is None


def test_compute_morning_score_excludes_very_negative_sentiment():
    assert compute_morning_score(85, -0.25, 0.6) is None


def test_compute_morning_score_bullish_gap_boosts():
    base = compute_morning_score(80, 0.0, 0.0)
    boosted = compute_morning_score(80, 0.0, 0.6)
    assert boosted is not None and base is not None
    assert boosted > base


def test_refine_morning_plan(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    pd.DataFrame([
        {"Stock": "M&M", "Sector": "Auto", "Close": 3400, "Score": 86,
         "Vol_Ratio": 2.3, "RSI": 67, "Liq_Cr": 800, "Dist_EMA20": 6.2},
        {"Stock": "GAIL", "Sector": "Energy", "Close": 181, "Score": 85,
         "Vol_Ratio": 4.4, "RSI": 66, "Liq_Cr": 150, "Dist_EMA20": 4.4},
    ]).to_csv("screener_results.csv", index=False)

    pd.DataFrame([
        {"symbol": "M&M", "sentiment_7d": 0.15, "has_neg_reg_news_7d": False},
        {"symbol": "GAIL", "sentiment_7d": -0.25, "has_neg_reg_news_7d": False},
    ]).to_csv("news_features.csv", index=False)

    json.dump({"M&M": "2031", "GAIL": "4717"}, open("nse_eq_mapping.json", "w"))
    json.dump(
        {"trading_date": "2026-08-01", "symbols": {"M&M": "2031", "GAIL": "4717"}},
        open("trade_plan.json", "w"),
    )
    Path("market_regime.txt").write_text("NEUTRAL-BEAR")

    monkeypatch.setattr(
        "hermes.pipelines.steps.morning_refiner.market_db.get_latest_gap_prediction",
        lambda: {"prediction_pct": 0.8, "bias": "Strong Bullish Open"},
    )
    monkeypatch.setattr("hermes.pipelines.steps.morning_refiner.trading_date_ist", lambda: date(2026, 8, 3))

    plan = morning_refiner.refine_morning_plan()

    assert plan["trading_date"] == "2026-08-03"
    assert "M&M" in plan["symbols"]
    assert "GAIL" not in plan["symbols"]  # excluded: sentiment too negative
    assert (work / "morning_trade_plan.json").exists()


def test_load_active_trade_plan_prefers_morning(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setattr("hermes.clock.trading_date_ist", lambda: date(2026, 8, 3))

    json.dump({"trading_date": "2026-08-02", "symbols": {"OLD": "1"}}, open("trade_plan.json", "w"))
    json.dump(
        {"trading_date": "2026-08-03", "symbols": {"M&M": "2031"}},
        open("morning_trade_plan.json", "w"),
    )

    from hermes.config import get_config
    get_config.cache_clear()
    cfg = get_config()
    assert cfg.load_active_trade_plan() == {"M&M": "2031"}
    get_config.cache_clear()
