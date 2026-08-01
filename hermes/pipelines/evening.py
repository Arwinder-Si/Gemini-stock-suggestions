"""
Evening pipeline — screener, trade plan, persistence, and notification.

Mirrors the full VM evening sequence (``run_evening.sh``) as an idempotent,
manifest-tracked pipeline shared by VM cron and GitHub Actions. Steps gated on
``MONGODB_URI`` are skipped automatically where analytics storage is absent
(e.g. GitHub Actions).
"""

from __future__ import annotations

import sys
from datetime import date

from hermes import artifacts
from hermes.pipelines.runner import Step, run_steps

PY = sys.executable
M = "-m"


def _sqlite_persist() -> None:
    """Persist screener and news CSVs into the operational SQLite database."""
    from hermes.data import market_db

    for csv in ("screener_results.csv", "screener_results_smallcap.csv"):
        try:
            market_db.save_screener_results(csv)
        except FileNotFoundError:
            pass
    try:
        market_db.save_news_results("news_features.csv")
    except FileNotFoundError:
        pass


def build_steps() -> list[Step]:
    return [
        Step("security_ids", argv=[PY, M, "hermes.pipelines.steps.update_security_ids"], outputs=["nse_eq_mapping.json"]),
        Step("news", argv=[PY, M, "hermes.pipelines.steps.news_sentiment"], outputs=["news_features.csv", "news_raw_articles.csv"]),
        Step(
            "screener_large",
            argv=[PY, M, "hermes.pipelines.steps.comprehensive_screener", "--universe", "large"],
            outputs=["screener_results.csv", "market_regime.txt"],
        ),
        Step(
            "trade_plan_large",
            argv=[PY, M, "hermes.pipelines.steps.intraday_trigger", "--universe", "large"],
            outputs=["trade_plan.json"],
        ),
        Step(
            "screener_small",
            argv=[PY, M, "hermes.pipelines.steps.comprehensive_screener", "--universe", "small"],
            outputs=["screener_results_smallcap.csv"],
        ),
        Step(
            "trade_plan_small",
            argv=[PY, M, "hermes.pipelines.steps.intraday_trigger", "--universe", "small"],
            outputs=["trade_plan_smallcap.json"],
        ),
        Step(
            "persist_picks",
            argv=[PY, M, "hermes.pipelines.steps.persist_picks", "--source", "evening"],
            optional_env="MONGODB_URI",
        ),
        Step("market_snapshot", argv=[PY, M, "hermes.pipelines.steps.market_snapshot_job"], optional_env="MONGODB_URI"),
        Step("outcome_enricher", argv=[PY, M, "hermes.pipelines.steps.outcome_enricher"], optional_env="MONGODB_URI"),
        Step("sqlite_persist", func=_sqlite_persist),
        Step("notify_evening", argv=[PY, M, "hermes.integrations.notify_webex", "evening"]),
    ]


def run(trading_date: date, *, force: bool = False, skip: set[str] | None = None) -> None:
    run_steps(build_steps(), trading_date, force=force, skip=skip)
    artifacts.update_latest(trading_date)
