"""
Hermes command line — single entry point for all batch and live jobs.

    python -m hermes.cli evening [--date YYYY-MM-DD] [--force] [--skip a,b]
    python -m hermes.cli morning [--date YYYY-MM-DD] [--force] [--skip a,b]
    python -m hermes.cli live   [-- extra args passed to main.py]
    python -m hermes.cli pnl
    python -m hermes.cli chatops

VM cron, GitHub Actions, and ChatOps all invoke these same commands so there is
one definition of each pipeline.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime

from hermes.clock import trading_date_ist
from hermes.pipelines import evening, live, morning, pnl

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_skip(value: str | None) -> set[str]:
    if not value:
        return set()
    return {name.strip() for name in value.split(",") if name.strip()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("evening", "morning"):
        p = sub.add_parser(name, help=f"Run the {name} pipeline")
        p.add_argument("--date", type=_parse_date, default=None, help="Trading date (YYYY-MM-DD); defaults to today IST")
        p.add_argument("--force", action="store_true", help="Re-run steps already marked complete")
        p.add_argument("--skip", default=None, help="Comma-separated step names to skip")

    sub.add_parser("live", help="Launch the live agent (main.py)")
    sub.add_parser("pnl", help="Send the end-of-day P&L report")
    sub.add_parser("chatops", help="Run the Webex ChatOps poller (outbound API)")

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # For `live`, everything after the subcommand passes through to main.py.
    if argv and argv[0] == "live":
        live.run(argv[1:])
        return 0  # unreachable: execvp replaces the process

    if argv and argv[0] == "chatops":
        os.execvp(sys.executable, [sys.executable, "-m", "hermes.integrations.chatops"])
        return 0  # unreachable

    args = build_parser().parse_args(argv)

    if args.command == "evening":
        trading_date = args.date or trading_date_ist()
        evening.run(trading_date, force=args.force, skip=_parse_skip(args.skip))
    elif args.command == "morning":
        trading_date = args.date or trading_date_ist()
        morning.run(trading_date, force=args.force, skip=_parse_skip(args.skip))
    elif args.command == "pnl":
        pnl.run()

    return 0


if __name__ == "__main__":
    sys.exit(main())
