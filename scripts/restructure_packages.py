#!/usr/bin/env python3
"""
One-time migration: move flat root modules into hermes/ subpackages and rewrite imports.

Run from repo root:
    python scripts/restructure_packages.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# destination relative to hermes/
MOVES: dict[str, str] = {
    "config.py": "config.py",
    "clock.py": "clock.py",
    # domain
    "models.py": "domain/models.py",
    "strategy.py": "domain/strategy.py",
    "scoring.py": "domain/scoring.py",
    "costs.py": "domain/costs.py",
    "risk.py": "domain/risk.py",
    "orders.py": "domain/orders.py",
    "position_manager.py": "domain/position_manager.py",
    "universe.py": "domain/universe.py",
    # execution
    "broker.py": "execution/broker.py",
    "paper_broker.py": "execution/paper_broker.py",
    "dhan_broker.py": "execution/dhan_broker.py",
    "portfolio.py": "execution/portfolio.py",
    # data
    "market_db.py": "data/market_db.py",
    "data_cache.py": "data/data_cache.py",
    "analytics_models.py": "data/analytics_models.py",
    "analytics_store.py": "data/analytics_store.py",
    "analytics_mongo.py": "data/analytics_mongo.py",
    "logger.py": "data/logger.py",
    # live
    "main.py": "live/agent.py",
    "market_feed.py": "live/feed.py",
    "candle_recorder.py": "live/recorder.py",
    # integrations
    "auth_manager.py": "integrations/auth_manager.py",
    "notifier.py": "integrations/notifier.py",
    "notify_webex.py": "integrations/notify_webex.py",
    "webex_listener.py": "integrations/chatops.py",
    # pipeline steps
    "update_security_ids.py": "pipelines/steps/update_security_ids.py",
    "news_sentiment.py": "pipelines/steps/news_sentiment.py",
    "comprehensive_screener.py": "pipelines/steps/comprehensive_screener.py",
    "intraday_trigger.py": "pipelines/steps/intraday_trigger.py",
    "global_signals.py": "pipelines/steps/global_signals.py",
    "market_snapshot_job.py": "pipelines/steps/market_snapshot_job.py",
    "outcome_enricher.py": "pipelines/steps/outcome_enricher.py",
    # analytics
    "evaluation.py": "analytics/evaluation.py",
    "failure_analyzer.py": "analytics/failure_analyzer.py",
    "analytics_report.py": "analytics/analytics_report.py",
    "trade_journal.py": "analytics/trade_journal.py",
    "trade_journal_report.py": "analytics/trade_journal_report.py",
    "daily_report.py": "analytics/daily_report.py",
    # research
    "backtest.py": "research/backtest.py",
    "screener_backtest.py": "research/screener_backtest.py",
    "nse_backtester.py": "research/nse_backtester.py",
    "analyze_today.py": "research/analyze_today.py",
}

# old top-level module -> new import path (without leading hermes.)
IMPORT_MAP: dict[str, str] = {
    "config": "hermes.config",
    "clock": "hermes.clock",
    "models": "hermes.domain.models",
    "strategy": "hermes.domain.strategy",
    "scoring": "hermes.domain.scoring",
    "costs": "hermes.domain.costs",
    "risk": "hermes.domain.risk",
    "orders": "hermes.domain.orders",
    "position_manager": "hermes.domain.position_manager",
    "universe": "hermes.domain.universe",
    "broker": "hermes.execution.broker",
    "paper_broker": "hermes.execution.paper_broker",
    "dhan_broker": "hermes.execution.dhan_broker",
    "portfolio": "hermes.execution.portfolio",
    "market_db": "hermes.data.market_db",
    "data_cache": "hermes.data.data_cache",
    "analytics_models": "hermes.data.analytics_models",
    "analytics_store": "hermes.data.analytics_store",
    "analytics_mongo": "hermes.data.analytics_mongo",
    "logger": "hermes.data.logger",
    "market_feed": "hermes.live.feed",
    "candle_recorder": "hermes.live.recorder",
    "auth_manager": "hermes.integrations.auth_manager",
    "notifier": "hermes.integrations.notifier",
    "notify_webex": "hermes.integrations.notify_webex",
    "webex_listener": "hermes.integrations.chatops",
    "update_security_ids": "hermes.pipelines.steps.update_security_ids",
    "news_sentiment": "hermes.pipelines.steps.news_sentiment",
    "comprehensive_screener": "hermes.pipelines.steps.comprehensive_screener",
    "intraday_trigger": "hermes.pipelines.steps.intraday_trigger",
    "global_signals": "hermes.pipelines.steps.global_signals",
    "market_snapshot_job": "hermes.pipelines.steps.market_snapshot_job",
    "outcome_enricher": "hermes.pipelines.steps.outcome_enricher",
    "evaluation": "hermes.analytics.evaluation",
    "failure_analyzer": "hermes.analytics.failure_analyzer",
    "analytics_report": "hermes.analytics.analytics_report",
    "trade_journal": "hermes.analytics.trade_journal",
    "trade_journal_report": "hermes.analytics.trade_journal_report",
    "daily_report": "hermes.analytics.daily_report",
    "backtest": "hermes.research.backtest",
    "screener_backtest": "hermes.research.screener_backtest",
    "nse_backtester": "hermes.research.nse_backtester",
    "analyze_today": "hermes.research.analyze_today",
}

SUBPACKAGES = [
    "domain",
    "execution",
    "data",
    "live",
    "integrations",
    "pipelines/steps",
    "analytics",
    "research",
]


def move_files() -> None:
    hermes = ROOT / "hermes"
    for sub in SUBPACKAGES:
        (hermes / sub).mkdir(parents=True, exist_ok=True)
        init = hermes / sub / "__init__.py"
        if not init.exists():
            init.write_text('"""Hermes subpackage."""\n', encoding="utf-8")

    for src_name, dest_rel in MOVES.items():
        src = ROOT / src_name
        dest = hermes / dest_rel
        if not src.exists():
            if dest.exists():
                continue
            raise FileNotFoundError(f"Missing source: {src}")
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dest)
        print(f"MOVED {src_name} -> hermes/{dest_rel}")


def rewrite_imports_in_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    # Skip rewriting hermes.* imports that already point correctly
    for mod, new_path in sorted(IMPORT_MAP.items(), key=lambda x: -len(x[0])):
        # from module import ...
        text = re.sub(
            rf"^from {re.escape(mod)} import ",
            f"from {new_path} import ",
            text,
            flags=re.MULTILINE,
        )
        # import module (as ...)
        text = re.sub(
            rf"^import {re.escape(mod)}(\s|$)",
            rf"import {new_path.replace('.', '.')} as {mod}\1",
            text,
            flags=re.MULTILINE,
        )
        # Fix double-rewrite: "import hermes.x as hermes.x" edge cases
        text = text.replace(f"import {new_path} as {new_path}", f"import {new_path}")

    # Fix accidental double hermes.hermes.
    text = re.sub(r"from hermes\.hermes\.", "from hermes.", text)
    text = re.sub(r"import hermes\.hermes\.", "import hermes.", text)

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def rewrite_all_imports() -> None:
    patterns = ["**/*.py"]
    changed = 0
    for pat in patterns:
        for path in ROOT.glob(pat):
            if ".test-venv" in str(path) or "venv" in str(path):
                continue
            if path.name == "restructure_packages.py":
                continue
            if rewrite_imports_in_file(path):
                print(f"IMPORTS {path.relative_to(ROOT)}")
                changed += 1
    print(f"Updated imports in {changed} files")


def create_root_main() -> None:
    shim = ROOT / "main.py"
    shim.write_text(
        '"""Root entry point — delegates to the live agent."""\n\n'
        "from hermes.live.agent import main\n\n"
        'if __name__ == "__main__":\n'
        "    main()\n",
        encoding="utf-8",
    )
    print("WROTE root main.py shim")


def main() -> None:
    move_files()
    rewrite_all_imports()
    create_root_main()
    print("Done. Run: pytest tests/ -q")


if __name__ == "__main__":
    main()
