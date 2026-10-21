"""Calling window utilities for campaign scheduling.

Provides helpers to determine whether the current time falls within a
campaign's configured calling window and to compute the delay until
the next window opening.
"""

from datetime import datetime, time, timedelta
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from loguru import logger


def parse_hhmm(hhmm: str) -> time:
    """Parse an "HH:MM" string into a datetime.time object."""
    parts = hhmm.strip().split(":")
    return time(int(parts[0]), int(parts[1]))


def is_within_calling_window(
    window_start: Optional[str],
    window_end: Optional[str],
    timezone_str: Optional[str] = "UTC",
) -> bool:
    """Return True if the current time is inside the calling window.

    If no window is configured (both start/end are None), returns True (24/7 mode).
    """
    if not window_start or not window_end:
        return True

    try:
        tz = ZoneInfo(timezone_str or "UTC")
    except Exception:
        logger.warning(f"Invalid timezone '{timezone_str}', falling back to UTC")
        tz = ZoneInfo("UTC")

    now_local = datetime.now(tz).time()
    start = parse_hhmm(window_start)
    end = parse_hhmm(window_end)

    if start <= end:
        # Normal window (e.g. 09:00 - 17:00)
        return start <= now_local <= end
    else:
        # Overnight window (e.g. 22:00 - 06:00)
        return now_local >= start or now_local <= end


def seconds_until_window_opens(
    window_start: Optional[str],
    window_end: Optional[str],
    timezone_str: Optional[str] = "UTC",
) -> Optional[float]:
    """Compute seconds until the calling window opens.

    Returns None if the window is currently open or not configured.
    """
    if not window_start or not window_end:
        return None

    if is_within_calling_window(window_start, window_end, timezone_str):
        return None

    try:
        tz = ZoneInfo(timezone_str or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")

    now_dt = datetime.now(tz)
    start = parse_hhmm(window_start)

    # Build next window open as a full datetime
    next_open = now_dt.replace(
        hour=start.hour, minute=start.minute, second=0, microsecond=0
    )
    if next_open <= now_dt:
        next_open += timedelta(days=1)

    delta = (next_open - now_dt).total_seconds()
    return max(delta, 0)
