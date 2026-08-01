"""
Weekly performance report for evening and morning pipeline stock picks.

Runs every Friday at 5 PM IST (via cron) to summarize how recommended stocks
performed during the trading week — separate from paper-trade P&L.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import asdict
from datetime import date, timedelta

from hermes.analytics.evaluation import compute_aggregate_metrics, label_recommendation_outcome
from hermes.analytics.pick_tracker import (
    PICK_EVENING_LARGE,
    PICK_EVENING_SMALL,
    PICK_MORNING,
    get_analytics_store,
)
from hermes.clock import now_ist, trading_date_ist
from hermes.data.analytics_models import Recommendation, RecommendationOutcome
from hermes.pipelines.steps.outcome_enricher import enrich_due_picks

logger = logging.getLogger(__name__)

SOURCE_LABELS = {
    PICK_EVENING_LARGE: "Evening (Large/Mid)",
    PICK_EVENING_SMALL: "Evening (Small Cap)",
    PICK_MORNING: "Morning Refiner",
}


def week_range(ref: date | None = None) -> tuple[date, date]:
    """Monday–Friday of the ISO week containing ref (defaults to today IST)."""
    ref = ref or trading_date_ist()
    monday = ref - timedelta(days=ref.weekday())
    friday = monday + timedelta(days=4)
    return monday, friday


def _outcome_from_eval(doc: dict) -> RecommendationOutcome | None:
    raw = doc.get("outcome")
    if not raw:
        return None
    return RecommendationOutcome(**raw)


def _rec_from_eval(store, doc: dict) -> Recommendation | None:
    rec_id = doc.get("recommendation_id", "")
    if not rec_id:
        return None
    for rec in store.get_pipeline_picks():
        if rec.recommendation_id == rec_id:
            return rec
    return Recommendation(
        recommendation_id=rec_id,
        trading_date=doc.get("trading_date", ""),
        symbol=doc.get("symbol", ""),
        pick_source=doc.get("pick_source", ""),
        strategy="PIPELINE",
    )


def generate_weekly_pick_report(
    start_date: date | None = None,
    end_date: date | None = None,
    *,
    store=None,
) -> str:
    """Build markdown report for pipeline picks in the given date range."""
    store = store or get_analytics_store()
    if store is None:
        return (
            "## Weekly Pipeline Pick Report\n\n"
            "MongoDB not configured (`MONGODB_URI` not set). "
            "Pipeline pick tracking requires MongoDB Atlas."
        )

    if start_date is None or end_date is None:
        start_date, end_date = week_range()

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    picks = store.get_pipeline_picks(start_str, end_str)
    evaluations = store.get_evaluations(start_str, end_str)
    eval_by_id = {e["recommendation_id"]: e for e in evaluations}

    lines = [
        f"## Weekly Pipeline Pick Report",
        f"**Week:** {start_str} to {end_str}",
        f"**Generated:** {now_ist().strftime('%Y-%m-%d %H:%M:%S IST')}",
        "",
        "_Tracks evening screener and morning refiner picks — not live paper trades._",
        "",
    ]

    if not picks:
        lines.append("No pipeline picks recorded for this week.")
        return "\n".join(lines)

    # Summary by source
    by_source: dict[str, list] = defaultdict(list)
    for p in picks:
        by_source[p.pick_source].append(p)

    evaluated_count = sum(1 for p in picks if p.recommendation_id in eval_by_id)
    trade_evals = []
    for ev_doc in evaluations:
        outcome = _outcome_from_eval(ev_doc)
        if not outcome:
            continue
        rec = _rec_from_eval(store, ev_doc)
        if rec and outcome:
            trade_evals.append(label_recommendation_outcome(rec, outcome))

    metrics = compute_aggregate_metrics(trade_evals)

    lines.extend([
        "### Summary",
        f"- **Total picks:** {len(picks)}",
        f"- **Evaluated:** {evaluated_count} / {len(picks)}",
        f"- **Win rate:** {metrics.win_rate:.0f}%",
        f"- **Avg gain (winners):** {metrics.avg_return_pct:+.2f}%",
        f"- **Avg loss (losers):** {metrics.avg_loss_pct:+.2f}%",
        "",
        "| Source | Picks | Evaluated |",
        "|--------|-------|-----------|",
    ])

    for source in (PICK_EVENING_LARGE, PICK_EVENING_SMALL, PICK_MORNING):
        source_picks = by_source.get(source, [])
        if not source_picks:
            continue
        src_eval = sum(1 for p in source_picks if p.recommendation_id in eval_by_id)
        label = SOURCE_LABELS.get(source, source)
        lines.append(f"| {label} | {len(source_picks)} | {src_eval} |")

    lines.extend([
        "",
        "### Pick Performance",
        "",
        "| Date | Source | Symbol | Score | Return | Max Gain | Label |",
        "|------|--------|--------|-------|--------|----------|-------|",
    ])

    for pick in sorted(picks, key=lambda p: (p.trading_date, p.pick_source, p.symbol)):
        ev = eval_by_id.get(pick.recommendation_id)
        score = pick.confidence_score or pick.supporting_indicators.get("screener_score", "")
        source_label = SOURCE_LABELS.get(pick.pick_source, pick.pick_source)
        if ev:
            ret = ev.get("return_pct", 0)
            max_gain = ev.get("outcome", {}).get("max_gain_pct", "—")
            label = ev.get("outcome_label", "—")
            ret_str = f"{ret:+.2f}%"
        else:
            ret_str = "pending"
            max_gain = "—"
            label = "—"
        lines.append(
            f"| {pick.trading_date} | {source_label} | {pick.symbol} | {score} | "
            f"{ret_str} | {max_gain} | {label} |"
        )

    if trade_evals:
        best = max(trade_evals, key=lambda e: e.return_pct)
        worst = min(trade_evals, key=lambda e: e.return_pct)
        lines.extend([
            "",
            "### Highlights",
            f"- **Best pick:** {best.symbol} ({best.return_pct:+.2f}%)",
            f"- **Worst pick:** {worst.symbol} ({worst.return_pct:+.2f}%)",
        ])

    return "\n".join(lines)


def run_weekly_analytics(*, post_webex: bool = True) -> str:
    """Enrich missing outcomes for the week, generate report, optionally post to Webex."""
    store = get_analytics_store()
    if store is None:
        msg = generate_weekly_pick_report()
        if post_webex:
            _post_webex(msg)
        return msg

    monday, friday = week_range()
    enriched = enrich_due_picks(store, through_date=friday)
    logger.info("Enriched %d pipeline pick(s) before weekly report", enriched)

    report = generate_weekly_pick_report(monday, friday, store=store)
    if post_webex:
        _post_webex(report)
    return report


def _post_webex(markdown: str) -> None:
    try:
        from hermes.integrations.notify_webex import send_webex_message
        send_webex_message(markdown)
    except Exception as exc:
        logger.error("Failed to post weekly report to Webex: %s", exc)


def print_weekly_report() -> str:
    """Entry point for ChatOps /weekly command."""
    report = run_weekly_analytics(post_webex=False)
    print(report)
    return report
