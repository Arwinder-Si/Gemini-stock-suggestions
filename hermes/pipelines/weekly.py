"""Weekly pipeline pick analytics — Friday 5 PM IST report."""

from __future__ import annotations

import logging

from hermes.analytics.weekly_pick_report import run_weekly_analytics

logger = logging.getLogger(__name__)


def run(*, post_webex: bool = True) -> None:
    report = run_weekly_analytics(post_webex=post_webex)
    logger.info("Weekly pick report generated (%d chars)", len(report))
