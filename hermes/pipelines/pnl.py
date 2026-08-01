"""End-of-day P&L report."""

from __future__ import annotations

import subprocess
import sys


def run() -> None:
    subprocess.run([sys.executable, "-m", "hermes.integrations.notify_webex", "pnl"], check=True)
