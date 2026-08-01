"""
Live agent launcher.

Replaces the current process with the live agent module via ``execvp`` so that
signals (SIGTERM from ``timeout`` on the VM, SIGINT on the console) reach the
agent directly and its existing graceful-shutdown handlers run unchanged.
"""

from __future__ import annotations

import os
import sys


def run(extra_args: list[str] | None = None) -> None:
    argv = [sys.executable, "-m", "hermes.live.agent", *(extra_args or [])]
    os.execvp(argv[0], argv)
