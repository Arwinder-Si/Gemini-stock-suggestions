"""
Morning pipeline — overnight global signals and the pre-market briefing.

Mirrors the VM ``run_morning.sh`` sequence. ``global_signals.py`` persists its
own gap prediction to SQLite, so no separate persistence step is needed.
"""

from __future__ import annotations

import sys
from datetime import date

from hermes.pipelines.runner import Step, run_steps

PY = sys.executable
M = "-m"


def build_steps() -> list[Step]:
    return [
        Step("global_signals", argv=[PY, M, "hermes.pipelines.steps.global_signals"]),
        Step(
            "morning_refiner",
            argv=[PY, M, "hermes.pipelines.steps.morning_refiner"],
            outputs=["morning_trade_plan.json"],
        ),
        Step("notify_morning", argv=[PY, M, "hermes.integrations.notify_webex", "morning"]),
    ]


def run(trading_date: date, *, force: bool = False, skip: set[str] | None = None) -> None:
    run_steps(build_steps(), trading_date, force=force, skip=skip)
