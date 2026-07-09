"""
CSV signal logger — thread-safe append of generated signals.
"""

import csv
import logging
import os
import threading

from models import Signal

logger = logging.getLogger(__name__)

LOG_FILE = "signals.csv"
_write_lock = threading.Lock()


def init_logger() -> None:
    """Creates the CSV file with headers if it doesn't already exist."""
    if not os.path.isfile(LOG_FILE):
        with _write_lock, open(LOG_FILE, mode="w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "symbol", "direction", "entry", "sl", "tp", "reason"])
        logger.info("Initialised signal log: %s", LOG_FILE)


def log_signal(signal: Signal) -> None:
    """Appends a signal row to the CSV log (thread-safe)."""
    with _write_lock, open(LOG_FILE, mode="a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            signal.timestamp,
            signal.symbol,
            signal.direction,
            signal.entry,
            signal.sl,
            signal.tp,
            signal.reason,
        ])
    logger.debug("Logged signal: %s %s @ %s", signal.direction, signal.symbol, signal.timestamp)
