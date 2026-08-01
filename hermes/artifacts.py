"""
Run artifacts and idempotency manifest.

Every pipeline run is keyed by trading date and recorded under
``var/runs/<YYYY-MM-DD>/manifest.json``. The manifest tracks per-step status so
a re-run can skip work already completed. Declared step outputs are copied into
the run directory so each run is self-contained, and ``var/state/latest`` points
at the most recent successful run for downstream consumers (live agent, morning
pipeline).

The var directory defaults to ``./var`` relative to the current working
directory (pipelines run from the repo root). Override with ``HERMES_VAR_DIR``
for tests or alternate deployments.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import date, datetime
from pathlib import Path

from hermes.clock import now_ist

STEP_OK = "ok"
STEP_FAILED = "failed"
STEP_SKIPPED = "skipped"


def var_dir() -> Path:
    """Root directory for all runtime artifacts."""
    return Path(os.environ.get("HERMES_VAR_DIR", "var"))


def runs_dir() -> Path:
    return var_dir() / "runs"


def state_dir() -> Path:
    return var_dir() / "state"


def run_dir(trading_date: date) -> Path:
    """Directory holding one trading day's artifacts and manifest."""
    return runs_dir() / trading_date.strftime("%Y-%m-%d")


def manifest_path(trading_date: date) -> Path:
    return run_dir(trading_date) / "manifest.json"


def latest_link() -> Path:
    return state_dir() / "latest"


def load_manifest(trading_date: date) -> dict:
    """Load the manifest for a trading date, or a fresh skeleton if absent."""
    path = manifest_path(trading_date)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "trading_date": trading_date.strftime("%Y-%m-%d"),
        "started_at": now_ist().isoformat(),
        "steps": {},
    }


def save_manifest(trading_date: date, manifest: dict) -> None:
    run_dir(trading_date).mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = now_ist().isoformat()
    with open(manifest_path(trading_date), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def is_step_done(manifest: dict, step_name: str) -> bool:
    """True when a step previously completed successfully (skips are re-attempted)."""
    return manifest.get("steps", {}).get(step_name, {}).get("status") == STEP_OK


def record_step(
    manifest: dict,
    step_name: str,
    status: str,
    *,
    outputs: list[str] | None = None,
    reason: str | None = None,
    error: str | None = None,
) -> None:
    """Record the outcome of a step in the manifest (in place)."""
    entry: dict = {"status": status, "finished_at": now_ist().isoformat()}
    if outputs:
        entry["outputs"] = outputs
    if reason:
        entry["reason"] = reason
    if error:
        entry["error"] = error
    manifest.setdefault("steps", {})[step_name] = entry


def copy_outputs(trading_date: date, outputs: list[str]) -> list[str]:
    """
    Copy declared output files from the working directory into the run dir.

    Missing files are skipped silently — not every step produces every output
    (e.g. an empty screener). Returns the names actually copied.
    """
    dest_dir = run_dir(trading_date)
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in outputs:
        src = Path(name)
        if src.exists():
            shutil.copy2(src, dest_dir / src.name)
            copied.append(src.name)
    return copied


def update_latest(trading_date: date) -> None:
    """Point ``var/state/latest`` at the given trading date's run directory."""
    state_dir().mkdir(parents=True, exist_ok=True)
    link = latest_link()
    # Relative target keeps the symlink valid if var/ is relocated.
    target = os.path.relpath(run_dir(trading_date), state_dir())
    if link.is_symlink() or link.exists():
        link.unlink()
    os.symlink(target, link)


def latest_run_dir() -> Path | None:
    """Resolve the current ``latest`` run directory, or None if unset."""
    link = latest_link()
    if link.is_symlink() or link.exists():
        return link.resolve()
    return None


# ── Kill switch ──────────────────────────────────────────────────────────
# Primary location is ``var/state/KILL_SWITCH``; the repo-root path is honored
# as a fallback for backward compatibility.

_ROOT_KILL_SWITCH = Path("KILL_SWITCH")


def kill_switch_path() -> Path:
    return state_dir() / "KILL_SWITCH"


def _kill_switch_locations() -> list[Path]:
    return [kill_switch_path(), _ROOT_KILL_SWITCH]


def kill_switch_active() -> Path | None:
    """Return the path of an active kill switch sentinel, or None."""
    for path in _kill_switch_locations():
        if path.exists():
            return path
    return None


def write_kill_switch(message: str) -> Path:
    """Create the kill switch sentinel under var/state and return its path."""
    state_dir().mkdir(parents=True, exist_ok=True)
    path = kill_switch_path()
    path.write_text(message, encoding="utf-8")
    return path


def clear_kill_switch() -> None:
    """Remove the kill switch sentinel from all known locations."""
    for path in _kill_switch_locations():
        try:
            path.unlink()
        except OSError:
            pass
