"""
Idempotent step runner.

A pipeline is an ordered list of :class:`Step` objects. Each step either shells
out to an existing script (``argv``) or runs an inline callable (``func``).
Results are recorded in the run manifest so a re-run skips steps already marked
``ok`` unless ``force`` is set. Steps gated on an environment variable
(e.g. ``MONGODB_URI``) are skipped, not failed, when that variable is absent.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from hermes import artifacts

logger = logging.getLogger(__name__)


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def _optional_env_satisfied(var_name: str) -> bool:
    """True when an env var is set in the process environment or .env (via Settings)."""
    if os.environ.get(var_name, "").strip():
        return True
    if var_name == "MONGODB_URI":
        from hermes.config import get_config
        return bool(get_config().mongodb_uri)
    return False


@dataclass
class Step:
    """One unit of pipeline work.

    Exactly one of ``argv`` or ``func`` must be provided.
    """

    name: str
    argv: list[str] | None = None
    func: Callable[[], None] | None = None
    outputs: list[str] = field(default_factory=list)
    optional_env: str | None = None

    def run(self) -> None:
        if self.argv is not None:
            subprocess.run(self.argv, check=True)
        elif self.func is not None:
            self.func()
        else:  # pragma: no cover - guarded at construction time
            raise ValueError(f"Step {self.name} has neither argv nor func")


def run_steps(
    steps: list[Step],
    trading_date: date,
    *,
    force: bool = False,
    skip: set[str] | None = None,
) -> dict:
    """Execute steps in order, recording each outcome in the manifest.

    Raises the underlying exception if a required step fails (after recording it).
    Returns the final manifest.
    """
    _load_dotenv()
    skip = set(skip or [])
    manifest = artifacts.load_manifest(trading_date)

    for step in steps:
        if step.name in skip:
            logger.info("Skipping step %s (requested via --skip)", step.name)
            artifacts.record_step(manifest, step.name, artifacts.STEP_SKIPPED, reason="skip flag")
            artifacts.save_manifest(trading_date, manifest)
            continue

        if artifacts.is_step_done(manifest, step.name) and not force:
            logger.info("Skipping step %s (already completed)", step.name)
            continue

        if step.optional_env and not _optional_env_satisfied(step.optional_env):
            logger.info("Skipping step %s (no %s)", step.name, step.optional_env)
            artifacts.record_step(
                manifest, step.name, artifacts.STEP_SKIPPED, reason=f"no {step.optional_env}"
            )
            artifacts.save_manifest(trading_date, manifest)
            continue

        logger.info("Running step %s", step.name)
        try:
            step.run()
        except Exception as exc:
            logger.exception("Step %s failed", step.name)
            artifacts.record_step(manifest, step.name, artifacts.STEP_FAILED, error=str(exc))
            artifacts.save_manifest(trading_date, manifest)
            raise

        copied = artifacts.copy_outputs(trading_date, step.outputs)
        artifacts.record_step(manifest, step.name, artifacts.STEP_OK, outputs=copied)
        artifacts.save_manifest(trading_date, manifest)

    return manifest
