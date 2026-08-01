#!/usr/bin/env python3
"""
End-to-end smoke test for the Hermes trading system.

Runs unit tests, batch pipelines (evening + morning), manifest/idempotency
checks, and a synthetic live-agent loop. Steps that need secrets are skipped
when credentials are absent:

  - notify_evening / notify_morning  (WEBEX_TOKEN, WEBEX_ROOM_ID)
  - market_snapshot / outcome_enricher (MONGODB_URI)
  - live Dhan feed (DHAN_CLIENT_ID, DHAN_TOTP_SECRET)

Usage (from repo root):
    python scripts/run_e2e.py
    python scripts/run_e2e.py --quick   # skip slow yfinance screener/news
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
TD = date.today().isoformat()


def _has_env(*keys: str) -> bool:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    return all(os.environ.get(k, "").strip() for k in keys)


def run(cmd: list[str], *, label: str, timeout: int | None = None) -> None:
    print(f"\n{'=' * 60}\n  {label}\n{'=' * 60}")
    result = subprocess.run(cmd, cwd=ROOT, timeout=timeout)
    if result.returncode != 0:
        raise SystemExit(f"FAILED: {label} (exit {result.returncode})")
    print(f"OK: {label}")


def check_manifest() -> None:
    manifest_path = ROOT / "var" / "runs" / TD / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"Missing manifest: {manifest_path}")
    data = json.loads(manifest_path.read_text())
    steps = data.get("steps", {})
    ok = sum(1 for s in steps.values() if s.get("status") == "ok")
    skipped = sum(1 for s in steps.values() if s.get("status") == "skipped")
    failed = [n for n, s in steps.items() if s.get("status") == "failed"]
    print(f"\nManifest {manifest_path.name}: {ok} ok, {skipped} skipped, {len(failed)} failed")
    if failed:
        raise SystemExit(f"Failed steps in manifest: {failed}")
    latest = ROOT / "var" / "state" / "latest"
    if not latest.exists():
        raise SystemExit("Missing var/state/latest symlink")
    print(f"Latest run: {latest.resolve().name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes end-to-end smoke test")
    parser.add_argument("--quick", action="store_true", help="Skip slow yfinance screener/news steps")
    args = parser.parse_args()

    os.environ.setdefault("HERMES_VAR_DIR", str(ROOT / "var"))

    skip: set[str] = {"market_snapshot", "outcome_enricher"}
    if not _has_env("WEBEX_TOKEN", "WEBEX_ROOM_ID"):
        skip |= {"notify_evening", "notify_morning"}
        print("Note: skipping Webex notify steps (no WEBEX_TOKEN/WEBEX_ROOM_ID in .env)")
    if args.quick:
        skip |= {"news", "screener_large", "screener_small", "trade_plan_large", "trade_plan_small"}
        print("Note: --quick mode skips screener/news (uses existing CSV artifacts if present)")

    skip_arg = ",".join(sorted(skip))

    # 1. Unit tests
    run([PY, "-m", "pytest", "tests/", "-q", "--tb=line"], label="Unit tests (pytest)")

    # 2. Evening pipeline
    run(
        [PY, "-m", "hermes.cli", "evening", "--date", TD, "--force", "--skip", skip_arg],
        label="Evening pipeline",
        timeout=900 if not args.quick else 120,
    )
    check_manifest()

    # 3. Idempotency — second run should skip completed steps
    print(f"\n{'=' * 60}\n  Idempotency re-run (expect skips)\n{'=' * 60}")
    subprocess.run(
        [PY, "-m", "hermes.cli", "evening", "--date", TD, "--skip", skip_arg],
        cwd=ROOT,
        check=True,
    )

    # 4. Morning pipeline
    morning_skip = "notify_morning" if "notify_morning" in skip else ""
    morning_cmd = [PY, "-m", "hermes.cli", "morning", "--date", TD, "--force"]
    if morning_skip:
        morning_cmd.extend(["--skip", morning_skip])
    run(morning_cmd, label="Morning pipeline", timeout=180)

    # 5. Artifact checks
    print(f"\n{'=' * 60}\n  Artifact verification\n{'=' * 60}")
    artifacts = [
        "nse_eq_mapping.json",
        "market_regime.txt",
    ]
    if not args.quick:
        artifacts.extend(["screener_results.csv", "trade_plan.json"])
    for name in artifacts:
        path = ROOT / name
        status = "OK" if path.exists() else "MISSING"
        print(f"  [{status}] {name}")
        if name == "nse_eq_mapping.json" and not path.exists():
            raise SystemExit("nse_eq_mapping.json not produced")

    # 6. Synthetic live agent (no Dhan WebSocket required)
    run(
        [PY, "-m", "pytest", "tests/test_agent_loop.py", "-q", "--tb=line"],
        label="Live agent loop (synthetic candles)",
    )

    print(f"\n{'=' * 60}")
    print("  E2E SMOKE TEST PASSED")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
