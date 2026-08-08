"""
Earnings / results calendar for NSE universe stocks.

Uses yfinance ticker.calendar (free, no API key) plus headline date parsing from
news_features.csv. Output is earnings_calendar.json consumed by morning refiner,
Webex briefings, and pick persistence metadata.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

CALENDAR_FILE = "earnings_calendar.json"

_MONTH_NAMES = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# Headline patterns: "results on 8 August 2026", "August 8, 2026", "08-Aug-2026"
_HEADLINE_DATE_PATTERNS = [
    re.compile(
        r"\b(?:results?|earnings|board\s+meeting)\s+(?:on|scheduled\s+(?:on|for)|due\s+on|to\s+be\s+(?:held|announced)\s+on)\s+"
        r"(\d{1,2})[\s\-/]+([A-Za-z]+)(?:[\s\-/,]+(\d{4}))?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:results?|earnings|board\s+meeting)\s+(?:on|scheduled\s+(?:on|for)|due\s+on|to\s+be\s+(?:held|announced)\s+on)\s+"
        r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:[\s,]+(\d{4}))?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:[\s,]+(\d{4}))?\b.*?\b(?:results?|earnings|quarterly)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(\d{1,2})[\-/]([A-Za-z]{3,9})[\-/](\d{4})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(\d{1,2})[\-/](\d{1,2})[\-/](\d{4})\b",
    ),
]


def _parse_month(name: str) -> int | None:
    return _MONTH_NAMES.get(name.strip().lower())


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_result_date_from_headline(headline: str, ref: date) -> date | None:
    """Best-effort parse of a results date from a news headline."""
    if not headline:
        return None

    for pattern in _HEADLINE_DATE_PATTERNS:
        match = pattern.search(headline)
        if not match:
            continue
        groups = match.groups()

        if len(groups) == 3 and groups[0] and groups[1] and groups[2]:
            g0, g1, g2 = groups
            if g0.isdigit() and g1.isdigit() and g2.isdigit() and len(g0) <= 2 and len(g1) <= 2:
                parsed = _safe_date(int(g2), int(g1), int(g0))
            elif g0.isdigit() and not str(g1).isdigit():
                month = _parse_month(str(g1))
                year = int(g2) if g2 else ref.year
                parsed = _safe_date(year, month, int(g0)) if month else None
            elif not str(g0).isdigit() and str(g1).isdigit():
                month = _parse_month(str(g0))
                year = int(g2) if g2 else ref.year
                parsed = _safe_date(year, month, int(g1)) if month else None
            else:
                parsed = None
        elif len(groups) >= 2:
            g0, g1 = groups[0], groups[1]
            year_s = groups[2] if len(groups) > 2 else None
            year = int(year_s) if year_s else ref.year
            if g0.isdigit() and not str(g1).isdigit():
                month = _parse_month(str(g1))
                parsed = _safe_date(year, month, int(g0)) if month else None
            elif not str(g0).isdigit() and g1.isdigit():
                month = _parse_month(str(g0))
                parsed = _safe_date(year, month, int(g1)) if month else None
            else:
                parsed = None
        else:
            parsed = None

        if parsed and parsed >= ref - timedelta(days=7):
            return parsed

    return None


def fetch_yfinance_earnings_date(symbol: str, ref: date) -> date | None:
    """Return the nearest upcoming earnings date from yfinance calendar."""
    import yfinance as yf

    try:
        cal = yf.Ticker(f"{symbol}.NS").calendar
    except Exception as exc:
        logger.debug("yfinance calendar failed for %s: %s", symbol, exc)
        return None

    if not cal or not isinstance(cal, dict):
        return None

    raw = cal.get("Earnings Date")
    if raw is None:
        return None

    dates: list[date] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, date):
                dates.append(item)
            elif hasattr(item, "date"):
                dates.append(item.date())
    elif isinstance(raw, date):
        dates.append(raw)
    elif hasattr(raw, "date"):
        dates.append(raw.date())

    future = [d for d in dates if d >= ref - timedelta(days=1)]
    if not future:
        return None
    return min(future)


def _merge_entry(
    entries: dict[str, dict[str, Any]],
    symbol: str,
    result_date: date,
    source: str,
) -> None:
    existing = entries.get(symbol)
    if existing:
        old = date.fromisoformat(existing["result_date"])
        if result_date >= old:
            entries[symbol] = {"result_date": result_date.isoformat(), "source": source}
    else:
        entries[symbol] = {"result_date": result_date.isoformat(), "source": source}


def bucket_symbols(entries: dict[str, dict[str, Any]], ref: date) -> tuple[list[str], list[str]]:
    """Return (result_today, result_tomorrow) symbol lists for ref date."""
    today: list[str] = []
    tomorrow: list[str] = []
    next_day = ref + timedelta(days=1)
    for symbol, meta in entries.items():
        rd = date.fromisoformat(meta["result_date"])
        if rd == ref:
            today.append(symbol)
        elif rd == next_day:
            tomorrow.append(symbol)
    return sorted(today), sorted(tomorrow)


def build_calendar_document(
    symbols: list[str],
    ref: date,
    *,
    news_rows: list[dict[str, Any]] | None = None,
    fetch_delay_sec: float = 0.12,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build full earnings calendar by querying yfinance and parsing news."""
    entries: dict[str, dict[str, Any]] = {}
    news_by_symbol: dict[str, list[str]] = {}
    if news_rows:
        for row in news_rows:
            sym = str(row.get("symbol", "")).strip()
            headline = str(row.get("top_headline", "") or "")
            if sym and headline:
                news_by_symbol.setdefault(sym, []).append(headline)

    for symbol in symbols:
        yf_date = fetch_yfinance_earnings_date(symbol, ref)
        if yf_date:
            _merge_entry(entries, symbol, yf_date, "yfinance")
        if fetch_delay_sec > 0:
            time.sleep(fetch_delay_sec)

    for symbol, headlines in news_by_symbol.items():
        best: date | None = None
        for headline in headlines:
            parsed = parse_result_date_from_headline(headline, ref)
            if parsed and (best is None or parsed < best):
                best = parsed
        if best:
            _merge_entry(entries, symbol, best, "news")

    result_today, result_tomorrow = bucket_symbols(entries, ref)

    return {
        "generated_at": generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
        "as_of_date": ref.isoformat(),
        "entries": entries,
        "result_today": result_today,
        "result_tomorrow": result_tomorrow,
    }


def load_calendar(path: str = CALENDAR_FILE) -> dict[str, Any] | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_calendar(doc: dict[str, Any], path: str = CALENDAR_FILE) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)


def refresh_buckets(doc: dict[str, Any], ref: date) -> dict[str, Any]:
    """Recompute result_today / result_tomorrow for ref without re-fetching."""
    entries = doc.get("entries") or {}
    today, tomorrow = bucket_symbols(entries, ref)
    doc = dict(doc)
    doc["as_of_date"] = ref.isoformat()
    doc["result_today"] = today
    doc["result_tomorrow"] = tomorrow
    return doc


def is_result_day(symbol: str, trading_date: str, calendar: dict[str, Any] | None) -> bool:
    """True if symbol reports results on trading_date (YYYY-MM-DD)."""
    if not calendar:
        return False
    entry = (calendar.get("entries") or {}).get(symbol)
    if not entry:
        return False
    return entry.get("result_date") == trading_date


def symbols_for_session(calendar: dict[str, Any] | None, session: str) -> list[str]:
    """session: 'today' | 'tomorrow'"""
    if not calendar:
        return []
    key = "result_today" if session == "today" else "result_tomorrow"
    return list(calendar.get(key) or [])
