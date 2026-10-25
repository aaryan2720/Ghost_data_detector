"""Timestamp parsing, normalization, and cutoff evaluation.

Ghost Data Still Exists: deterministic timestamp handling.
All timestamps are normalized to UTC.
"""

from datetime import datetime, timezone
import re
from typing import Optional

ISO_FORMAT_REGEX = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$"
)


class InvalidTimestampError(ValueError):
    """Raised when a timestamp cannot be parsed or normalized."""
    pass


def parse_iso_timestamp(ts_str: str) -> datetime:
    """Parse an ISO-8601 timestamp string into a timezone-aware UTC datetime.
    
    Accepts formats such as:
      - 2026-08-18T09:14:00Z
      - 2026-08-18T09:14:00+00:00
      - 2026-08-18T09:14:00.123456Z
      - 2026-08-18 09:14:00Z
    
    Raises:
      InvalidTimestampError: If the timestamp is empty, invalid, or malformed.
    """
    if not ts_str or not isinstance(ts_str, str):
        raise InvalidTimestampError(f"Timestamp must be a non-empty string, got: {ts_str!r}")
    
    clean_ts = ts_str.strip()
    if not clean_ts:
        raise InvalidTimestampError("Timestamp cannot be blank")

    # Replace space separator with 'T'
    if " " in clean_ts and "T" not in clean_ts:
        clean_ts = clean_ts.replace(" ", "T", 1)

    # If ending with 'Z', Python's fromisoformat in 3.11 handles it, but normalize consistently
    try:
        if clean_ts.endswith("Z"):
            dt = datetime.fromisoformat(clean_ts[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(clean_ts)
    except Exception as e:
        raise InvalidTimestampError(f"Cannot parse timestamp '{ts_str}': {e}") from e

    # Ensure timezone awareness; if naive, assume UTC as challenge data is UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    return dt


def is_at_or_before(candidate_ts: str | datetime, cutoff_ts: str | datetime) -> bool:
    """Check if candidate timestamp is at or before cutoff timestamp (inclusive).
    
    Both inputs can be ISO-8601 strings or datetime objects.
    Returns True if candidate <= cutoff.
    """
    c_dt = parse_iso_timestamp(candidate_ts) if isinstance(candidate_ts, str) else candidate_ts
    cut_dt = parse_iso_timestamp(cutoff_ts) if isinstance(cutoff_ts, str) else cutoff_ts
    
    if c_dt.tzinfo is None:
        c_dt = c_dt.replace(tzinfo=timezone.utc)
    else:
        c_dt = c_dt.astimezone(timezone.utc)
        
    if cut_dt.tzinfo is None:
        cut_dt = cut_dt.replace(tzinfo=timezone.utc)
    else:
        cut_dt = cut_dt.astimezone(timezone.utc)

    return c_dt <= cut_dt


def is_strictly_after(candidate_ts: str | datetime, cutoff_ts: str | datetime) -> bool:
    """Check if candidate timestamp is strictly after cutoff timestamp (>)."""
    return not is_at_or_before(candidate_ts, cutoff_ts)
