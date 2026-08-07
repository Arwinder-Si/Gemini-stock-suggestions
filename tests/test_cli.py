"""Tests for the Hermes CLI, step runner, and pipeline definitions."""

from __future__ import annotations

from datetime import date

import pytest

from hermes import artifacts, cli
from hermes.pipelines import evening, morning
from hermes.pipelines.runner import Step, run_steps

TD = date(2026, 8, 1)


@pytest.fixture
def var_root(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("HERMES_VAR_DIR", str(tmp_path / "var"))
    monkeypatch.delenv("MONGODB_URI", raising=False)
    return tmp_path


# ── Runner behaviour ─────────────────────────────────────────────────────

def test_run_steps_executes_in_order(var_root):
    calls: list[str] = []
    steps = [
        Step("a", func=lambda: calls.append("a")),
        Step("b", func=lambda: calls.append("b")),
        Step("c", func=lambda: calls.append("c")),
    ]

    manifest = run_steps(steps, TD)

    assert calls == ["a", "b", "c"]
    assert all(manifest["steps"][s]["status"] == "ok" for s in ("a", "b", "c"))


def test_run_steps_skips_completed_unless_forced(var_root):
    counter = {"n": 0}
    steps = [Step("once", func=lambda: counter.__setitem__("n", counter["n"] + 1))]

    run_steps(steps, TD)
    assert counter["n"] == 1

    # Second run skips the already-completed step.
    run_steps(steps, TD)
    assert counter["n"] == 1

    # --force re-runs it.
    run_steps(steps, TD, force=True)
    assert counter["n"] == 2


def test_run_steps_skips_optional_env_when_missing(var_root, monkeypatch):
    calls: list[str] = []
    steps = [Step("mongo", func=lambda: calls.append("mongo"), optional_env="MONGODB_URI")]

    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setattr("hermes.pipelines.runner._load_dotenv", lambda: None)
    monkeypatch.setattr(
        "hermes.config.get_config",
        lambda: type("Cfg", (), {"mongodb_uri": ""})(),
    )

    manifest = run_steps(steps, TD)

    assert calls == []
    assert manifest["steps"]["mongo"]["status"] == "skipped"
    assert "MONGODB_URI" in manifest["steps"]["mongo"]["reason"]


def test_run_steps_honors_skip_set(var_root):
    calls: list[str] = []
    steps = [
        Step("keep", func=lambda: calls.append("keep")),
        Step("drop", func=lambda: calls.append("drop")),
    ]

    manifest = run_steps(steps, TD, skip={"drop"})

    assert calls == ["keep"]
    assert manifest["steps"]["drop"]["status"] == "skipped"


def test_run_steps_records_failure_and_raises(var_root):
    def boom() -> None:
        raise RuntimeError("kaboom")

    steps = [Step("bad", func=boom)]

    with pytest.raises(RuntimeError, match="kaboom"):
        run_steps(steps, TD)

    manifest = artifacts.load_manifest(TD)
    assert manifest["steps"]["bad"]["status"] == "failed"
    assert "kaboom" in manifest["steps"]["bad"]["error"]


def test_run_steps_copies_outputs(var_root):
    def write_output() -> None:
        (var_root / "work" / "trade_plan.json").write_text('{"symbols": {}}')

    steps = [Step("plan", func=write_output, outputs=["trade_plan.json"])]
    run_steps(steps, TD)

    assert (artifacts.run_dir(TD) / "trade_plan.json").exists()


def test_run_steps_invokes_subprocess(var_root, monkeypatch):
    recorded: list[list[str]] = []

    def fake_run(argv, check):
        recorded.append(argv)

    monkeypatch.setattr("hermes.pipelines.runner.subprocess.run", fake_run)

    steps = [
        Step("one", argv=["python", "-m", "hermes.pipelines.steps.global_signals"]),
        Step("two", argv=["python", "-m", "hermes.integrations.notify_webex", "morning"]),
    ]
    run_steps(steps, TD)

    assert recorded == [
        ["python", "-m", "hermes.pipelines.steps.global_signals"],
        ["python", "-m", "hermes.integrations.notify_webex", "morning"],
    ]


# ── Pipeline definitions ─────────────────────────────────────────────────

def test_evening_step_order():
    names = [s.name for s in evening.build_steps()]
    assert names == [
        "security_ids",
        "news",
        "screener_large",
        "trade_plan_large",
        "screener_small",
        "trade_plan_small",
        "persist_picks",
        "market_snapshot",
        "outcome_enricher",
        "sqlite_persist",
        "notify_evening",
    ]


def test_evening_optional_steps_gated_on_mongo():
    gated = {s.name: s.optional_env for s in evening.build_steps() if s.optional_env}
    assert gated == {
        "persist_picks": "MONGODB_URI",
        "market_snapshot": "MONGODB_URI",
        "outcome_enricher": "MONGODB_URI",
    }


def test_morning_step_order():
    names = [s.name for s in morning.build_steps()]
    assert names == ["global_signals", "morning_refiner", "persist_picks", "notify_morning"]


def test_evening_run_updates_latest(var_root, monkeypatch):
    monkeypatch.setattr(evening, "run_steps", lambda *a, **k: {})
    evening.run(TD)

    resolved = artifacts.latest_run_dir()
    assert resolved is not None
    assert resolved.name == "2026-08-01"


def test_morning_run_does_not_update_latest(var_root, monkeypatch):
    monkeypatch.setattr(morning, "run_steps", lambda *a, **k: {})
    morning.run(TD)

    assert artifacts.latest_run_dir() is None


# ── CLI argument handling ────────────────────────────────────────────────

def test_cli_evening_passes_date_and_flags(monkeypatch):
    captured = {}

    def fake_run(trading_date, *, force, skip):
        captured["date"] = trading_date
        captured["force"] = force
        captured["skip"] = skip

    monkeypatch.setattr(cli.evening, "run", fake_run)

    rc = cli.main(["evening", "--date", "2026-08-01", "--force", "--skip", "news,outcome_enricher"])

    assert rc == 0
    assert captured["date"] == TD
    assert captured["force"] is True
    assert captured["skip"] == {"news", "outcome_enricher"}


def test_cli_evening_defaults_to_today(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli.evening, "run", lambda td, **k: captured.update(date=td))
    monkeypatch.setattr(cli, "trading_date_ist", lambda: date(2026, 12, 25))

    cli.main(["evening"])

    assert captured["date"] == date(2026, 12, 25)


def test_cli_pnl_invoked(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(cli.pnl, "run", lambda: called.__setitem__("n", called["n"] + 1))

    assert cli.main(["pnl"]) == 0
    assert called["n"] == 1


def test_parse_skip_empty():
    assert cli._parse_skip(None) == set()
    assert cli._parse_skip("") == set()
    assert cli._parse_skip("a, b ,c") == {"a", "b", "c"}
