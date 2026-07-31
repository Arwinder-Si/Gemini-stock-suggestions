"""
Timezone and market clock utilities (IST / Asia/Kolkata).
"""

from datetime import datetime, date, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

def now_ist() -> datetime:
    """Return current timezone-aware datetime in IST."""
    return datetime.now(IST)

def trading_date_ist() -> date:
    """Return current date in IST."""
    return now_ist().date()

def parse_time_ist(time_str: str) -> time:
    """Parse HH:MM string to time object."""
    return datetime.strptime(time_str, "%H:%M").time()
