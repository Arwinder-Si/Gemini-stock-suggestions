"""Tests for the run manifest and artifact helpers."""

from __future__ import annotations

import os
from datetime import date

import pytest

from hermes import artifacts


@pytest.fixture
def var_root(tmp_path, monkeypatch):
    """Isolate var/ under a temp dir and run from a clean working directory."""
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("HERMES_VAR_DIR", str(tmp_path / "var"))
    return tmp_path


TD = date(2026, 8, 1)


def test_manifest_create_load_save(var_root):
    manifest = artifacts.load_manifest(TD)
    assert manifest["trading_date"] == "2026-08-01"
    assert manifest["steps"] == {}

    artifacts.record_step(manifest, "screener_large", artifacts.STEP_OK, outputs=["screener_results.csv"])
    artifacts.save_manifest(TD, manifest)

    reloaded = artifacts.load_manifest(TD)
    assert reloaded["steps"]["screener_large"]["status"] == "ok"
    assert reloaded["steps"]["screener_large"]["outputs"] == ["screener_results.csv"]
    assert "finished_at" in reloaded["steps"]["screener_large"]
    assert "updated_at" in reloaded


def test_is_step_done(var_root):
    manifest = artifacts.load_manifest(TD)
    assert not artifacts.is_step_done(manifest, "news")

    artifacts.record_step(manifest, "news", artifacts.STEP_OK)
    assert artifacts.is_step_done(manifest, "news")

    # A skipped step is not "done" — it should be retried on re-run.
    artifacts.record_step(manifest, "market_snapshot", artifacts.STEP_SKIPPED, reason="no MONGODB_URI")
    assert not artifacts.is_step_done(manifest, "market_snapshot")

    # A failed step is not "done".
    artifacts.record_step(manifest, "notify_evening", artifacts.STEP_FAILED, error="boom")
    assert not artifacts.is_step_done(manifest, "notify_evening")


def test_copy_outputs_skips_missing(var_root):
    (var_root / "work" / "screener_results.csv").write_text("Stock,Score\nRELIANCE,80\n")

    copied = artifacts.copy_outputs(TD, ["screener_results.csv", "does_not_exist.json"])

    assert copied == ["screener_results.csv"]
    dest = artifacts.run_dir(TD) / "screener_results.csv"
    assert dest.exists()
    assert "RELIANCE" in dest.read_text()


def test_update_latest_symlink(var_root):
    artifacts.run_dir(TD).mkdir(parents=True, exist_ok=True)
    (artifacts.run_dir(TD) / "trade_plan.json").write_text("{}")

    artifacts.update_latest(TD)

    resolved = artifacts.latest_run_dir()
    assert resolved is not None
    assert resolved.name == "2026-08-01"
    assert (resolved / "trade_plan.json").exists()


def test_update_latest_repoints(var_root):
    older = date(2026, 7, 31)
    for d in (older, TD):
        artifacts.run_dir(d).mkdir(parents=True, exist_ok=True)

    artifacts.update_latest(older)
    assert artifacts.latest_run_dir().name == "2026-07-31"

    artifacts.update_latest(TD)
    assert artifacts.latest_run_dir().name == "2026-08-01"
