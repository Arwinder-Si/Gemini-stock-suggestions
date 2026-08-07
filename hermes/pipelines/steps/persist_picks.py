"""
Persist evening or morning pipeline picks to MongoDB for weekly performance tracking.
"""

from __future__ import annotations

import argparse
import logging
import sys

from hermes.analytics.pick_tracker import (
    backfill_picks_from_runs,
    get_analytics_store,
    persist_evening_picks,
    persist_morning_picks,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Persist pipeline stock picks to MongoDB")
    parser.add_argument(
        "--source",
        choices=["evening", "morning", "all"],
        default="all",
        help="Which pipeline picks to persist",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Also load picks from var/runs/*/ archived trade plans",
    )
    args = parser.parse_args(argv)

    store = get_analytics_store()
    if store is None:
        logger.error("MONGODB_URI not configured — cannot persist picks")
        return 1

    total = 0
    if args.backfill:
        total += backfill_picks_from_runs(store)
    if args.source in ("evening", "all"):
        total += persist_evening_picks(store)
    if args.source in ("morning", "all"):
        try:
            total += persist_morning_picks(store)
        except FileNotFoundError as exc:
            logger.warning("%s", exc)

    logger.info("Persisted %d pipeline pick(s) to MongoDB", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
