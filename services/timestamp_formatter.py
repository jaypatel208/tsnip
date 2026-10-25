"""Pure timestamp formatting utilities — single source of truth.

Replaces the duplicated format_timestamp / timestamp_to_seconds
functions that lived in both clip.py and monitor_streams.py.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from loguru import logger


def format_timestamp(start_time_str: str, user_time_str: str, delay: int) -> str:
    """Calculate HH:MM:SS (or MM:SS) offset from stream start.

    Args:
        start_time_str: Stream start time (ISO-8601, potentially with Z suffix).
        user_time_str: Time the user triggered the clip (ISO-8601).
        delay: Seconds to subtract (stream latency compensation).

    Returns:
        Formatted timestamp string, e.g. "01:23:45" or "12:34".
    """
    try:
        return hms(offset_seconds(start_time_str, user_time_str, delay))
    except Exception as exc:
        logger.error("Error formatting timestamp: {}", exc)
        return "00:00"


def offset_seconds(start_time_str: str, user_time_str: str, delay: int) -> int:
    """Seconds into the stream that *user_time_str* minus *delay* points at."""
    adjusted = _parse_iso(user_time_str) - timedelta(seconds=delay)
    return max(0, int((adjusted - _parse_iso(start_time_str)).total_seconds()))


def hms(total_seconds: int) -> str:
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{minutes:02}:{seconds:02}"


def comment_lines(entries: list[tuple[int, str, str]], window: int = 10) -> list[str]:
    """Turn (seconds, title, user) entries into comment lines, oldest first.

    Viewers react to one moment together (Lightor, arXiv 1910.12201), so
    entries within *window* seconds of the first one in a group become one
    line at the earliest time, keeping every title and every user once.
    """
    groups: list[list[tuple[int, str, str]]] = []
    for entry in sorted(entries, key=lambda e: e[0]):
        if groups and entry[0] - groups[-1][0][0] <= window:
            groups[-1].append(entry)
        else:
            groups.append([entry])

    lines = []
    for group in groups:
        titles = list(dict.fromkeys(t for _, t, _ in group if t))
        users = ", ".join(dict.fromkeys(u for _, _, u in group))
        ts = hms(group[0][0])
        if titles:
            lines.append(f"{ts} – _{' / '.join(titles)}_ (by {users})")
        else:
            lines.append(f"{ts} – (by {users})")
    return lines


def timestamp_to_seconds(timestamp: str) -> int:
    """Convert 'HH:MM:SS' or 'MM:SS' into total seconds."""
    try:
        parts = list(map(int, timestamp.split(":")))
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except (ValueError, AttributeError) as exc:
        logger.error("Error converting timestamp '{}': {}", timestamp, exc)
    return 0


def remove_custom_emojis(text: str) -> str:
    """Strip custom emoji patterns like :_EmojiName: from text."""
    if not text:
        return text
    return re.sub(r":_[^:]+:", "", text)


def remove_at_symbol(text: str) -> str:
    """Remove leading @ from usernames."""
    if not text:
        return text
    return text.lstrip("@")


# -- internal ---------------------------------------------------------------


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 string into a timezone-aware UTC datetime."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
