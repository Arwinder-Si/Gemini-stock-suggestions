#!/usr/bin/env python3
"""
Local smoke test for pipeline pick tracking + weekly report.

Simulates the VM bug (persist skipped) then backfills from var/runs archives.
Does NOT post to Webex unless --webex is passed.

Usage:
    python scripts/test_pick_flow_local.py
    python scripts/test_pick_flow_local.py --mongo   # also test against Atlas
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from hermes import artifacts
from hermes.analytics.weekly_pick_report import generate_weekly_pick_report, week_range
from hermes.analytics.pick_tracker import backfill_picks_from_runs
from hermes.data.analytics_mongo import InMemoryAnalyticsStore
from hermes.pipelines.runner import Step, run_steps


def _seed_run_archives(base: Path) -> None:
    """Create var/runs entries mimicking Mon–Thu evening pipelines for Aug 4–7 week."""
    samples = [
        ("2026-08-04", "2026-08-05", ["COCHINSHIP", "AWL", "NYKAA"]),
        ("2026-08-05", "2026-08-06", ["KOTAKBANK", "GRASIM", "WIPRO"]),
        ("2026-08-06", "2026-08-07", ["FEDERALBNK", "TATASTEEL", "HFCL"]),
    ]
    for run_date, trading_date, symbols in samples:
        run_dir = base / "var" / "runs" / run_date
        run_dir.mkdir(parents=True, exist_ok=True)
        plan = {"trading_date": trading_date, "symbols": {s: "1" for s in symbols}}
        (run_dir / "trade_plan.json").write_text(json.dumps(plan), encoding="utf-8")
        rows = [{
            "Stock": s,
            "Sector": "Test",
            "Close": 100.0 + i * 10,
            "Score": 80 + i,
            "Vol_Ratio": 2.0,
            "RSI": 65.0,
        } for i, s in enumerate(symbols)]
        pd.DataFrame(rows).to_csv(run_dir / "screener_results.csv", index=False)
        (run_dir / "market_regime.txt").write_text("NEUTRAL-BULL", encoding="utf-8")


def test_runner_runs_persist_when_mongo_in_dotenv_only(monkeypatch, tmp_path) -> bool:
    """Simulate cron: MONGODB_URI only in .env, not os.environ — persist must NOT skip."""
    os.chdir(tmp_path)
    os.environ["HERMES_VAR_DIR"] = str(tmp_path / "var")
    (tmp_path / ".env").write_text("MONGODB_URI=mongodb://fake-local/test\n", encoding="utf-8")
    monkeypatch.delenv("MONGODB_URI", raising=False)

    calls: list[str] = []

    class FakeCfg:
        mongodb_uri = "mongodb://fake-local/test"

    monkeypatch.setattr("hermes.config.get_config", lambda: FakeCfg())

    steps = [Step("persist_picks", func=lambda: calls.append("persist_picks"), optional_env="MONGODB_URI")]
    run_steps(steps, date(2026, 8, 7))

    ok = calls == ["persist_picks"]
    print(f"  runner env gate: {'PASS' if ok else 'FAIL'} (calls={calls})")
    return ok


def test_backfill_and_weekly_report(tmp_path) -> bool:
    os.chdir(tmp_path)
    os.environ["HERMES_VAR_DIR"] = str(tmp_path / "var")
    _seed_run_archives(tmp_path)

    store = InMemoryAnalyticsStore()
    count = backfill_picks_from_runs(store)
    picks = store.get_pipeline_picks("2026-08-05", "2026-08-07")

    mon, fri = week_range(date(2026, 8, 7))
    report = generate_weekly_pick_report(mon, fri, store=store)

    ok = count == 9 and len(picks) == 9 and "COCHINSHIP" in report and "Win rate" in report
    print(f"  backfill: {count} picks saved")
    print(f"  week range: {mon} to {fri}")
    print(f"  report length: {len(report)} chars")
    print(f"  backfill + report: {'PASS' if ok else 'FAIL'}")
    if not ok:
        print("--- report preview ---")
        print(report[:800])
    return ok


def test_mongo_backfill_real() -> bool:
    from hermes.analytics.pick_tracker import get_analytics_store

    store = get_analytics_store()
    if store is None:
        print("  mongo backfill: SKIP (no MONGODB_URI)")
        return True

    before = len(store.get_pipeline_picks("2026-08-03", "2026-08-07"))
    added = backfill_picks_from_runs(store)
    after = len(store.get_pipeline_picks("2026-08-03", "2026-08-07"))
    print(f"  mongo picks Aug 3-7: {before} -> {after} (+{added} from backfill)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mongo", action="store_true", help="Also run against real MongoDB Atlas")
    args = parser.parse_args()

    import pytest

    print("=== Local pick-tracking smoke test ===\n")

    results: list[bool] = []

    with pytest.MonkeyPatch.context() as mp:
        import tempfile
        td = Path(tempfile.mkdtemp())
        results.append(test_runner_runs_persist_when_mongo_in_dotenv_only(mp, td))

    with pytest.MonkeyPatch.context() as mp:
        import tempfile
        td = Path(tempfile.mkdtemp())
        results.append(test_backfill_and_weekly_report(td))

    print()
    print("=== pytest unit tests ===")
    rc = pytest.main(["-q", str(ROOT / "tests/test_pick_tracking.py"), str(ROOT / "tests/test_cli.py"), str(ROOT / "tests/test_analytics_store.py")])
    results.append(rc == 0)

    if args.mongo:
        print()
        print("=== MongoDB Atlas (live) ===")
        os.chdir(ROOT)
        os.environ.pop("HERMES_VAR_DIR", None)
        results.append(test_mongo_backfill_real())

    passed = sum(results)
    total = len(results)
    print()
    print(f"=== Overall: {passed}/{total} smoke checks passed ===")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
